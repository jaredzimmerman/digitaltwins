// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//! Strict RFC 8259 JSON parsing and canonical serialization for `.prsn`.
//!
//! The canonical form (spec `prsn.md`, "Canonical JSON") is the one byte form in
//! which manifests and `action_key` preimages are hashed and signed:
//!
//! - parsing rejects anything outside strict RFC 8259: bad UTF-8 (overlong
//!   forms, encoded surrogates, truncation), a leading BOM, raw U+0000..U+001F
//!   in strings, unknown escapes, lone/mispaired surrogate escapes, duplicate
//!   object keys at any depth, comments, `NaN`/`Infinity`, leading `+`,
//!   leading zeros, `.5`, `1.`, `1e`, trailing commas, trailing content, empty
//!   input, and number tokens that overflow a double;
//! - an integer token (no `.`, no exponent) that fits `i64` is an exact
//!   integer; any other number token is an IEEE-754 double, correctly rounded
//!   (underflow reads as zero);
//! - serialization: no whitespace; object keys sorted by Unicode code point
//!   (Rust `str` ordering is UTF-8 byte order, which equals code point order);
//!   minimal string escapes; integers in exact decimal (`-0` becomes `0`);
//!   doubles as shortest round-trip digits in ECMAScript
//!   `Number.prototype.toString` layout (`-0.0` becomes `0`; NaN and infinities
//!   cannot be serialized).

use std::collections::HashSet;

/// A JSON value. Objects keep insertion order; keys are sorted on serialization.
#[derive(Clone, Debug)]
pub enum Value {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    Array(Vec<Value>),
    Object(Vec<(String, Value)>),
}

impl Value {
    /// Look up a key in an object value.
    pub fn get(&self, key: &str) -> Option<&Value> {
        match self {
            Value::Object(pairs) => pairs.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    /// Look up a key in an object value, mutably.
    pub fn get_mut(&mut self, key: &str) -> Option<&mut Value> {
        match self {
            Value::Object(pairs) => pairs.iter_mut().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    /// Remove a key from an object value, returning the old value.
    pub fn remove(&mut self, key: &str) -> Option<Value> {
        match self {
            Value::Object(pairs) => {
                if let Some(i) = pairs.iter().position(|(k, _)| k == key) {
                    Some(pairs.remove(i).1)
                } else {
                    None
                }
            }
            _ => None,
        }
    }

    /// Insert or replace a key in an object value.
    pub fn set(&mut self, key: &str, value: Value) {
        match self {
            Value::Object(pairs) => {
                if let Some(slot) = pairs.iter_mut().find(|(k, _)| k == key) {
                    slot.1 = value;
                } else {
                    pairs.push((key.to_string(), value));
                }
            }
            _ => panic!("Value::set on non-object"),
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Value::Str(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_i64(&self) -> Option<i64> {
        match self {
            Value::Int(n) => Some(*n),
            _ => None,
        }
    }

    /// Numeric value as `f64`, converting exact integers.
    pub fn as_f64(&self) -> Option<f64> {
        match self {
            Value::Int(n) => Some(*n as f64),
            Value::Float(f) => Some(*f),
            _ => None,
        }
    }

    pub fn as_bool(&self) -> Option<bool> {
        match self {
            Value::Bool(b) => Some(*b),
            _ => None,
        }
    }

    pub fn as_array(&self) -> Option<&[Value]> {
        match self {
            Value::Array(a) => Some(a),
            _ => None,
        }
    }

    pub fn as_array_mut(&mut self) -> Option<&mut Vec<Value>> {
        match self {
            Value::Array(a) => Some(a),
            _ => None,
        }
    }

    pub fn as_object(&self) -> Option<&[(String, Value)]> {
        match self {
            Value::Object(o) => Some(o),
            _ => None,
        }
    }

    pub fn as_object_mut(&mut self) -> Option<&mut Vec<(String, Value)>> {
        match self {
            Value::Object(o) => Some(o),
            _ => None,
        }
    }

    pub fn is_object(&self) -> bool {
        matches!(self, Value::Object(_))
    }
}

/// Strict parse error with a byte position.
#[derive(Debug, Clone)]
pub struct ParseError {
    pub message: String,
    pub position: usize,
}

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "JSON parse error at byte {}: {}", self.position, self.message)
    }
}

impl std::error::Error for ParseError {}

/// Serialization error (only reachable for NaN/±Infinity).
#[derive(Debug, Clone)]
pub struct SerializeError(pub String);

impl std::fmt::Display for SerializeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "JSON serialization error: {}", self.0)
    }
}

impl std::error::Error for SerializeError {}

const MAX_DEPTH: usize = 512;

struct Parser<'a> {
    s: &'a str,
    b: &'a [u8],
    pos: usize,
}

impl<'a> Parser<'a> {
    fn err(&self, message: &str) -> ParseError {
        ParseError {
            message: message.to_string(),
            position: self.pos.min(self.b.len()),
        }
    }

    fn eof(&self) -> bool {
        self.pos >= self.b.len()
    }

    fn peek(&self) -> u8 {
        if self.eof() {
            0
        } else {
            self.b[self.pos]
        }
    }

    fn skip_ws(&mut self) {
        while matches!(self.peek(), b' ' | b'\t' | b'\n' | b'\r') {
            self.pos += 1;
        }
    }

    fn parse_value(&mut self, depth: usize) -> Result<Value, ParseError> {
        if depth > MAX_DEPTH {
            return Err(self.err("nesting too deep"));
        }
        match self.peek() {
            b'{' => self.parse_object(depth + 1),
            b'[' => self.parse_array(depth + 1),
            b'"' => Ok(Value::Str(self.parse_string()?)),
            b't' => self.parse_literal("true", Value::Bool(true)),
            b'f' => self.parse_literal("false", Value::Bool(false)),
            b'n' => self.parse_literal("null", Value::Null),
            b'-' | b'0'..=b'9' => self.parse_number(),
            _ => Err(self.err("unexpected character")),
        }
    }

    fn parse_literal(&mut self, word: &str, value: Value) -> Result<Value, ParseError> {
        if self.b.len() >= self.pos + word.len() && &self.b[self.pos..self.pos + word.len()] == word.as_bytes() {
            self.pos += word.len();
            Ok(value)
        } else {
            Err(self.err("invalid literal"))
        }
    }

    fn parse_string(&mut self) -> Result<String, ParseError> {
        // self.b[self.pos] == b'"'
        self.pos += 1;
        let mut out = String::new();
        loop {
            if self.eof() {
                return Err(self.err("unterminated string"));
            }
            match self.b[self.pos] {
                b'"' => {
                    self.pos += 1;
                    return Ok(out);
                }
                0x00..=0x1f => return Err(self.err("raw control character in string")),
                b'\\' => {
                    self.pos += 1;
                    if self.eof() {
                        return Err(self.err("unterminated string"));
                    }
                    match self.b[self.pos] {
                        b'"' => {
                            out.push('"');
                            self.pos += 1;
                        }
                        b'\\' => {
                            out.push('\\');
                            self.pos += 1;
                        }
                        b'/' => {
                            out.push('/');
                            self.pos += 1;
                        }
                        b'b' => {
                            out.push('\u{08}');
                            self.pos += 1;
                        }
                        b'f' => {
                            out.push('\u{0c}');
                            self.pos += 1;
                        }
                        b'n' => {
                            out.push('\n');
                            self.pos += 1;
                        }
                        b'r' => {
                            out.push('\r');
                            self.pos += 1;
                        }
                        b't' => {
                            out.push('\t');
                            self.pos += 1;
                        }
                        b'u' => {
                            self.pos += 1;
                            let cp = self.parse_hex4()?;
                            if (0xd800..=0xdbff).contains(&cp) {
                                // Must be followed immediately by a low-surrogate escape.
                                if self.b.len() < self.pos + 2
                                    || self.b[self.pos] != b'\\'
                                    || self.b[self.pos + 1] != b'u'
                                {
                                    return Err(self.err("lone high-surrogate escape"));
                                }
                                self.pos += 2;
                                let lo = self.parse_hex4()?;
                                if !(0xdc00..=0xdfff).contains(&lo) {
                                    return Err(self.err("mispaired surrogate escape"));
                                }
                                let ch = 0x10000 + ((cp - 0xd800) << 10) + (lo - 0xdc00);
                                out.push(char::from_u32(ch).unwrap());
                            } else if (0xdc00..=0xdfff).contains(&cp) {
                                return Err(self.err("lone low-surrogate escape"));
                            } else {
                                out.push(char::from_u32(cp).unwrap());
                            }
                        }
                        _ => return Err(self.err("unknown escape")),
                    }
                }
                _ => {
                    let ch = self.s[self.pos..].chars().next().unwrap();
                    out.push(ch);
                    self.pos += ch.len_utf8();
                }
            }
        }
    }

    fn parse_hex4(&mut self) -> Result<u32, ParseError> {
        if self.b.len() < self.pos + 4 {
            return Err(self.err("short \\u escape"));
        }
        let mut cp: u32 = 0;
        for i in 0..4 {
            let d = (self.b[self.pos + i] as char).to_digit(16);
            match d {
                Some(d) => cp = cp * 16 + d,
                None => return Err(self.err("bad hex digit in \\u escape")),
            }
        }
        self.pos += 4;
        Ok(cp)
    }

    fn parse_number(&mut self) -> Result<Value, ParseError> {
        let start = self.pos;
        if self.peek() == b'-' {
            self.pos += 1;
        }
        match self.peek() {
            b'0' => {
                self.pos += 1;
                if self.peek().is_ascii_digit() {
                    return Err(self.err("leading zero"));
                }
            }
            b'1'..=b'9' => {
                while self.peek().is_ascii_digit() {
                    self.pos += 1;
                }
            }
            _ => return Err(self.err("invalid number")),
        }
        let mut is_int = true;
        if self.peek() == b'.' {
            is_int = false;
            self.pos += 1;
            if !self.peek().is_ascii_digit() {
                return Err(self.err("dangling decimal point"));
            }
            while self.peek().is_ascii_digit() {
                self.pos += 1;
            }
        }
        if self.peek() == b'e' || self.peek() == b'E' {
            is_int = false;
            self.pos += 1;
            if self.peek() == b'+' || self.peek() == b'-' {
                self.pos += 1;
            }
            if !self.peek().is_ascii_digit() {
                return Err(self.err("dangling exponent"));
            }
            while self.peek().is_ascii_digit() {
                self.pos += 1;
            }
        }
        let token = &self.s[start..self.pos];
        if is_int {
            match token.parse::<i64>() {
                Ok(n) => Ok(Value::Int(n)),
                Err(_) => {
                    // Integer token that does not fit i64: read as a double.
                    let f: f64 = token.parse().map_err(|_| self.err("invalid number"))?;
                    if !f.is_finite() {
                        return Err(self.err("number token overflows a double"));
                    }
                    Ok(Value::Float(f))
                }
            }
        } else {
            let f: f64 = token.parse().map_err(|_| self.err("invalid number"))?;
            if !f.is_finite() {
                return Err(self.err("number token overflows a double"));
            }
            Ok(Value::Float(f))
        }
    }

    fn parse_array(&mut self, depth: usize) -> Result<Value, ParseError> {
        // self.b[self.pos] == b'['
        self.pos += 1;
        let mut items = Vec::new();
        self.skip_ws();
        if self.peek() == b']' {
            self.pos += 1;
            return Ok(Value::Array(items));
        }
        loop {
            self.skip_ws();
            items.push(self.parse_value(depth)?);
            self.skip_ws();
            match self.peek() {
                b',' => {
                    self.pos += 1;
                    self.skip_ws();
                    if self.peek() == b']' {
                        return Err(self.err("trailing comma"));
                    }
                }
                b']' => {
                    self.pos += 1;
                    return Ok(Value::Array(items));
                }
                _ => {
                    if self.eof() {
                        return Err(self.err("unterminated array"));
                    }
                    return Err(self.err("expected ',' or ']'"));
                }
            }
        }
    }

    fn parse_object(&mut self, depth: usize) -> Result<Value, ParseError> {
        // self.b[self.pos] == b'{'
        self.pos += 1;
        let mut pairs: Vec<(String, Value)> = Vec::new();
        let mut seen: HashSet<String> = HashSet::new();
        self.skip_ws();
        if self.peek() == b'}' {
            self.pos += 1;
            return Ok(Value::Object(pairs));
        }
        loop {
            self.skip_ws();
            if self.peek() != b'"' {
                if self.eof() {
                    return Err(self.err("unterminated object"));
                }
                return Err(self.err("expected string key"));
            }
            let key = self.parse_string()?;
            if !seen.insert(key.clone()) {
                return Err(self.err("duplicate object key"));
            }
            self.skip_ws();
            if self.peek() != b':' {
                return Err(self.err("expected ':'"));
            }
            self.pos += 1;
            self.skip_ws();
            let value = self.parse_value(depth)?;
            pairs.push((key, value));
            self.skip_ws();
            match self.peek() {
                b',' => {
                    self.pos += 1;
                    self.skip_ws();
                    if self.peek() == b'}' {
                        return Err(self.err("trailing comma"));
                    }
                }
                b'}' => {
                    self.pos += 1;
                    return Ok(Value::Object(pairs));
                }
                _ => {
                    if self.eof() {
                        return Err(self.err("unterminated object"));
                    }
                    return Err(self.err("expected ',' or '}'"));
                }
            }
        }
    }
}

/// Strictly parse `input` as RFC 8259 JSON.
pub fn parse(input: &[u8]) -> Result<Value, ParseError> {
    if input.len() >= 3 && input[0] == 0xef && input[1] == 0xbb && input[2] == 0xbf {
        return Err(ParseError {
            message: "leading byte-order mark".to_string(),
            position: 0,
        });
    }
    let s = std::str::from_utf8(input).map_err(|e| ParseError {
        message: format!("invalid UTF-8: {e}"),
        position: e.valid_up_to(),
    })?;
    let mut p = Parser {
        s,
        b: s.as_bytes(),
        pos: 0,
    };
    p.skip_ws();
    if p.eof() {
        return Err(p.err("empty input"));
    }
    let v = p.parse_value(0)?;
    p.skip_ws();
    if !p.eof() {
        return Err(p.err("trailing content"));
    }
    Ok(v)
}

/// Serialize `v` to canonical JSON bytes.
pub fn to_canonical(v: &Value) -> Result<Vec<u8>, SerializeError> {
    let mut out = Vec::new();
    write_value(v, &mut out)?;
    Ok(out)
}

fn write_value(v: &Value, out: &mut Vec<u8>) -> Result<(), SerializeError> {
    match v {
        Value::Null => out.extend_from_slice(b"null"),
        Value::Bool(true) => out.extend_from_slice(b"true"),
        Value::Bool(false) => out.extend_from_slice(b"false"),
        Value::Int(n) => out.extend_from_slice(n.to_string().as_bytes()),
        Value::Float(f) => out.extend_from_slice(format_double(*f)?.as_bytes()),
        Value::Str(s) => write_string(s, out),
        Value::Array(items) => {
            out.push(b'[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(b',');
                }
                write_value(item, out)?;
            }
            out.push(b']');
        }
        Value::Object(pairs) => {
            // Sort by Unicode code point. Rust `str` ordering is UTF-8 byte
            // order, which equals code point order.
            let mut items: Vec<&(String, Value)> = pairs.iter().collect();
            items.sort_by(|a, b| a.0.cmp(&b.0));
            out.push(b'{');
            for (i, (k, val)) in items.iter().enumerate() {
                if i > 0 {
                    out.push(b',');
                }
                write_string(k, out);
                out.push(b':');
                write_value(val, out)?;
            }
            out.push(b'}');
        }
    }
    Ok(())
}

fn write_string(s: &str, out: &mut Vec<u8>) {
    out.push(b'"');
    for c in s.chars() {
        match c {
            '"' => out.extend_from_slice(b"\\\""),
            '\\' => out.extend_from_slice(b"\\\\"),
            '\u{08}' => out.extend_from_slice(b"\\b"),
            '\u{09}' => out.extend_from_slice(b"\\t"),
            '\u{0a}' => out.extend_from_slice(b"\\n"),
            '\u{0c}' => out.extend_from_slice(b"\\f"),
            '\u{0d}' => out.extend_from_slice(b"\\r"),
            c if (c as u32) < 0x20 => {
                let esc = format!("\\u{:04x}", c as u32);
                out.extend_from_slice(esc.as_bytes());
            }
            c => {
                let mut buf = [0u8; 4];
                out.extend_from_slice(c.encode_utf8(&mut buf).as_bytes());
            }
        }
    }
    out.push(b'"');
}

/// Format a finite, non-zero double as shortest round-trip digits in
/// ECMAScript `Number.prototype.toString` layout.
pub fn format_double(f: f64) -> Result<String, SerializeError> {
    if !f.is_finite() {
        return Err(SerializeError("NaN and infinities cannot be serialised".to_string()));
    }
    if f == 0.0 {
        // Covers -0.0 as well.
        return Ok("0".to_string());
    }
    let neg = f < 0.0;
    // Shortest round-trip digits (unique for a given double).
    let mut buf = ryu::Buffer::new();
    let s = buf.format_finite(f.abs());
    let (mant, exp): (&str, i64) = match s.find(['e', 'E']) {
        Some(i) => {
            let e: i64 = s[i + 1..]
                .parse()
                .map_err(|_| SerializeError("bad exponent".to_string()))?;
            (&s[..i], e)
        }
        None => (s, 0),
    };
    let (ip, fp) = match mant.find('.') {
        Some(i) => (&mant[..i], &mant[i + 1..]),
        None => (mant, ""),
    };
    // digits d1..dk with value 0.d1..dk * 10^n.
    let mut digits = format!("{ip}{fp}");
    let mut n: i64 = ip.len() as i64 + exp;
    while digits.len() > 1 && digits.starts_with('0') {
        digits.remove(0);
        n -= 1;
    }
    while digits.len() > 1 && digits.ends_with('0') {
        digits.pop();
    }
    let k = digits.len() as i64;
    let body = if k <= n && n <= 21 {
        format!("{digits}{}", "0".repeat((n - k) as usize))
    } else if 0 < n && n <= 21 {
        format!("{}.{}", &digits[..n as usize], &digits[n as usize..])
    } else if -6 < n && n <= 0 {
        format!("0.{}{digits}", "0".repeat((-n) as usize))
    } else {
        let e = n - 1;
        let frac = if digits.len() > 1 {
            format!(".{}", &digits[1..])
        } else {
            String::new()
        };
        format!("{}{}e{}{}", &digits[..1], frac, if e >= 0 { "+" } else { "-" }, e.abs())
    };
    Ok(if neg { format!("-{body}") } else { body })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn canon(input: &str) -> String {
        let v = parse(input.as_bytes()).expect("parse");
        String::from_utf8(to_canonical(&v).expect("serialize")).expect("utf8")
    }

    #[test]
    fn sort_by_code_point_not_utf16() {
        // U+1F600 sorts after U+E000 by code point, before it in UTF-16.
        let v = parse("{\"\\ud83d\\ude00\":2,\"\\ue000\":1,\"\\u00e9\":3,\"z\":4}".as_bytes()).unwrap();
        assert_eq!(
            String::from_utf8(to_canonical(&v).unwrap()).unwrap(),
            "{\"z\":4,\"\u{e9}\":3,\"\u{e000}\":1,\"\u{1f600}\":2}"
        );
    }

    #[test]
    fn number_layouts() {
        assert_eq!(canon("1E30"), "1e+30");
        assert_eq!(canon("1e21"), "1e+21");
        assert_eq!(canon("1e20"), "100000000000000000000");
        assert_eq!(canon("0.000001"), "0.000001");
        assert_eq!(canon("1.25e-6"), "0.00000125");
        assert_eq!(canon("1.25e-7"), "1.25e-7");
        assert_eq!(canon("-0"), "0");
        assert_eq!(canon("-0.0"), "0");
        assert_eq!(canon("1.0"), "1");
        assert_eq!(canon("9007199254740993"), "9007199254740993");
        assert_eq!(canon("9007199254740993.0"), "9007199254740992");
        assert_eq!(canon("9223372036854775807"), "9223372036854775807");
        assert_eq!(canon("9223372036854775808"), "9223372036854776000");
        assert_eq!(canon("1e-400"), "0");
        assert_eq!(canon("5e-324"), "5e-324");
        assert_eq!(canon("1.7976931348623157e308"), "1.7976931348623157e+308");
        assert_eq!(canon("0.30000000000000004"), "0.30000000000000004");
        assert_eq!(canon("333333333.33333329"), "333333333.3333333");
    }

    #[test]
    fn strict_rejections() {
        for bad in [
            "{ \"a\": 1, \"a\": 2 }",
            "{\"a\":01}",
            "{\"a\":+1}",
            "{\"a\":.5}",
            "{\"a\":1.}",
            "{\"a\":1e}",
            "{\"a\":1,}",
            "[1,]",
            "{\"a\":NaN}",
            "{\"a\":Infinity}",
            "{\"a\":\"\\x\"}",
            "{\"a\":\"\\ud800\"}",
            "{\"a\":\"\\udc00\"}",
            "{\"a\":\"\\ud800x\"}",
            "{ 'a': 1 }",
            "{\"a\":1} trailing",
            "",
            "   ",
            "{\"a\":1e400}",
        ] {
            assert!(parse(bad.as_bytes()).is_err(), "should reject: {bad}");
        }
        assert!(parse(b"\xef\xbb\xbf{\"a\":1}").is_err());
        assert!(parse(b"\"\x01\"").is_err());
        // Overlong, encoded surrogate, truncated UTF-8.
        assert!(parse(b"\"\xc0\xaf\"").is_err());
        assert!(parse(b"\"\xed\xa0\x80\"").is_err());
        assert!(parse(b"\"\xe2\x82\"").is_err());
    }

    #[test]
    fn string_escapes() {
        assert_eq!(canon("\"\\u0000\\u001f\\u007f\""), "\"\\u0000\\u001f\x7f\"");
        assert_eq!(canon("\"a/b\""), "\"a/b\"");
        assert_eq!(canon("\"\u{2028}\u{2029}\""), "\"\u{2028}\u{2029}\"");
    }
}
