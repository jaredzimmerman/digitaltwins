/**
 * Twin: a wooden artist's mannequin on a plinth, and beside it its digital
 * twin, the same figure drawn in dots. The pointer picks a limb on either:
 * the mannequin raises it, and the twin follows a beat later. At rest the
 * mannequin stands in contrapposto, one hand on its hip, and its head takes
 * the bright stroke. The slider is the twin's lag, in ms.
 *
 * The pattern: one of many. Limbs are capsules (the hull of two projected
 * spheres) with ball joints, sorted by depth every frame; the hit test reads
 * the rest pose, so a raised arm cannot move out from under the pointer.
 */
const {
  Cam, facing, fit, hull, lerp, poly, proj, prism, put, rad, rings, seg, solid,
  tdone, tset, tval, tween, disposer, mk, pointer, register,
} = HL;

const S = 2.15, AX = [Math.SQRT1_2, -Math.SQRT1_2], FW = [Math.SQRT1_2, Math.SQRT1_2];
const FIGS = [{ a: -33, f: 6 }, { a: 33, f: -12 }]; // the mannequin, then its twin, a step behind
const LIMBS = ["head", "arm l", "arm r", "leg l", "leg r"];
// Degrees. Arms and legs: upper, lower segment, swung out to the side (0 hangs down, 180 points up). Head: tilt, nod.
const REST = { head: [7, 0], "arm l": [38, -48], "arm r": [8, 2], "leg l": [6, -1], "leg r": [2, 2] };
const RAISE = { head: [-12, -22], "arm l": [150, 172], "arm r": [150, 172], "leg l": [56, 34], "leg r": [56, 34] };

/** The figure's parts in world space for limb raises t: capsules {limb, p, q, ra, rb}, a ball when p is q. */
function body(fig, t) {
  const W = ([a, f, z]) => [AX[0] * (fig.a + a) + FW[0] * (fig.f + f), AX[1] * (fig.a + a) + FW[1] * (fig.f + f), z];
  const ang = (k) => REST[k].map((r, i) => rad(lerp(r, RAISE[k][i], t[k])));
  const add = (p, d, L) => [p[0] + d[0] * L, p[1] + d[1] * L, p[2] + d[2] * L];
  const parts = [], cap = (limb, p, q, ra, rb = ra) => parts.push({ limb, p: W(p), q: W(q), ra, rb, ball: p === q });
  cap(null, [-5, 0, 55], [5, 0, 55], 5.6); // pelvis
  cap(null, [0, 0, 62], [0, 0, 62], 3.6); // waist joint
  cap(null, [-4, 0, 74], [4, 0, 74], 8.4); // chest
  cap(null, [0, 0, 82], [0, 0, 88], 2.4); // neck
  const [tl, nd] = ang("head"), hd = [Math.sin(tl), Math.sin(nd), Math.cos(tl) * Math.cos(nd)];
  cap("head", add([0, 0, 88], hd, 5.6), add([0, 0, 88], hd, 11.2), 6.2, 5.8); // a faceless egg
  for (const side of [-1, 1]) {
    const arm = side < 0 ? "arm l" : "arm r", leg = side < 0 ? "leg l" : "leg r";
    const [a1, a2] = ang(arm), da = (x, fw) => [side * Math.sin(x), fw, -Math.cos(x)];
    const sh = [side * 12.6, 0.5, 79.5], el = add(sh, da(a1, 0.05), 17), wr = add(el, da(a2, 0.25), 15), hn = add(wr, da(a2, 0.25), 5);
    cap(arm, sh, sh, 3.9); cap(arm, sh, el, 3.0, 2.6); cap(arm, el, el, 3.2); cap(arm, el, wr, 2.6, 2.1); cap(arm, wr, hn, 2.4, 2.0);
    const [l1, l2] = ang(leg), dl = (x) => [side * Math.sin(x), 0, -Math.cos(x)];
    const hp = [side * 6.4, 0, 50.5], kn = add(hp, dl(l1), 22), an = add(kn, dl(l2), 21);
    cap(leg, hp, hp, 4.1); cap(leg, hp, kn, 3.9, 3.2); cap(leg, kn, kn, 3.6); cap(leg, kn, an, 3.1, 2.3);
    cap(leg, [an[0], an[1] - 1, an[2] - 1.5], [an[0], an[1] + 6.5, an[2] - 1.5], 2.5, 2.1); // foot
  }
  return parts;
}

const ring24 = (c, r) => Array.from({ length: 24 }, (_, k) => [c[0] + r * Math.cos((k / 24) * 2 * Math.PI), c[1] + r * Math.sin((k / 24) * 2 * Math.PI)]);
/** Nearer the camera is larger: across the ground toward the viewer, and up. Balls sit just over the limbs they join. */
const depth = (p) => ((p.p[0] + p.q[0] + p.p[1] + p.q[1]) / 2) * 0.612 + ((p.p[2] + p.q[2]) / 2) * 0.5 + (p.ball ? 0.9 : 0);

function mount({ stage, svg, read }, value) {
  const bag = disposer();
  let lag = value;
  const C = Cam(45, 0.5, S), box = [];
  for (const fig of FIGS) for (const [a, f, z] of [[-16, -12, 0], [16, -12, 0], [-16, 26, 0], [16, 26, 0], [-24, 0, 122], [24, 0, 122]])
    box.push([AX[0] * (fig.a + a) + FW[0] * (fig.f + f), AX[1] * (fig.a + a) + FW[1] * (fig.f + f), z]);
  fit(C, box, 200, 166);
  const P = proj(C), front = facing(C);
  const turn = (ring, fig) => ring.map((q) => ({ ...q,
    u: AX[0] * (fig.a + q.u) + FW[0] * (fig.f + q.v), v: AX[1] * (fig.a + q.u) + FW[1] * (fig.f + q.v),
    nu: AX[0] * q.nu + FW[0] * q.nv, nv: AX[1] * q.nu + FW[1] * q.nv }));

  const rest = Object.fromEntries(LIMBS.map((k) => [k, 0]));
  const figs = FIGS.map((fig, fi) => {
    const g = mk("g", {}, svg), twin = fi === 1;
    const [ring, inner] = rings(-15, -11, 15, 13, 6, 1.6);
    const plinth = solid(g);
    put(plinth, prism(P, front, turn(ring, fig), turn(inner, fig), 0, 4));
    if (twin) { plinth.sil.setAttribute("class", "dash"); plinth.cr.setAttribute("class", "nf dash"); }
    const els = body(fig, rest).map(() => {
      const pg = mk("g", {}, g);
      return { g: pg, sil: mk("path", { class: twin ? "dash" : "sil" }, pg), cr: twin ? null : mk("path", { class: "nf lo" }, pg) };
    });
    const tw = Object.fromEntries(LIMBS.map((k) => [k, tween(0)]));
    return { fig, g, twin, els, tw, order: "", drawn: "", rest: body(fig, rest) };
  });
  // A twin standing behind is painted first.
  figs[0].g.after(figs[1].g);

  function draw(F, now) {
    const t = Object.fromEntries(LIMBS.map((k) => [k, tval(F.tw[k], now)]));
    const key = LIMBS.map((k) => t[k].toFixed(3)).join();
    if (key === F.drawn) return;
    F.drawn = key;
    const parts = body(F.fig, t);
    parts.forEach((p, i) => {
      const a = P(...p.p), b = P(...p.q), el = F.els[i];
      el.sil.setAttribute("d", poly(hull(ring24(a, p.ra * S).concat(ring24(b, p.rb * S)))));
      if (!el.cr) return;
      // the crease: a dim line along the limb on its upper-left side, short of both ends
      const dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy);
      if (p.ball || len < 4) { el.cr.setAttribute("d", ""); return; }
      let nx = -dy / len, ny = dx / len;
      if (nx * -0.6 + ny * -0.8 < 0) { nx = -nx; ny = -ny; }
      const o = 0.5 * Math.min(p.ra, p.rb) * S, s0 = 0.18, s1 = 0.82;
      el.cr.setAttribute("d", seg([a[0] + dx * s0 + nx * o, a[1] + dy * s0 + ny * o], [a[0] + dx * s1 + nx * o, a[1] + dy * s1 + ny * o]));
    });
    // back to front: move the groups only when the order changes
    const idx = parts.map((p, i) => [depth(p), i]).sort((x, y) => x[0] - y[0]).map((x) => x[1]);
    const order = idx.join();
    if (order !== F.order) { F.order = order; idx.forEach((i) => F.g.appendChild(F.els[i].g)); }
  }

  const B = register(stage, (_dt, now) => {
    let moving = false;
    for (const F of figs) { draw(F, now); for (const k of LIMBS) if (!tdone(F.tw[k], now)) moving = true; }
    return moving;
  });
  bag.add(B.unregister);

  /** The limb whose rest pose, on either figure, passes nearest the point; null for none. */
  function hit([x, y]) {
    let best = null, bd = 6;
    for (const F of figs) for (const p of F.rest) {
      if (!p.limb) continue;
      const a = P(...p.p), b = P(...p.q), dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy || 1;
      const u = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / L2));
      const d = Math.hypot(x - a[0] - u * dx, y - a[1] - u * dy) - Math.max(p.ra, p.rb) * S;
      if (d < bd) { bd = d; best = p.limb; }
    }
    return best;
  }

  let act;
  const light = (limb) => figs[0].rest.forEach((p, i) => figs[0].els[i].sil.classList.toggle("hi", p.limb === limb));
  /** Raises one limb (null lowers them all); the twin copies it, lag ms later. */
  function setActive(limb) {
    if (limb === act) return;
    act = limb;
    const now = performance.now();
    figs.forEach((F, fi) => LIMBS.forEach((k) => tset(F.tw[k], k === limb ? 1 : 0, now, fi * lag)));
    light(limb || "head");
    read.textContent = limb || "rest";
    B.wake();
  }

  setActive(null);
  bag.add(pointer(stage, { move: (p) => setActive(hit(p)), leave: () => setActive(null) }));
  bag.add(() => svg.replaceChildren());

  return {
    set: (v) => { lag = v; },
    destroy: bag.dispose,
  };
}

hairline({
  name: "twin",
  means: "A wooden mannequin and its digital twin: point at a limb, the mannequin raises it, and the twin follows a beat later.",
  rules: [1, 2, 6, 9],
  range: [60, 180, 320],
  tour: [[131, 96], [161, 160], [286, 216], null],
  mount,
});
