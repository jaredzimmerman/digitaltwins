# digitaltwins

Open file formats for portable digital twins of people: one file that holds a person's
face, head and voice assets, together with the raw captures they were made from, so that
any application can read them and newer methods can re-derive the assets without a rescan.

| Format | What it is | Repository |
|---|---|---|
| `.prsn` | A person file: identity, face and head geometry, appearance (Gaussian splats, stills), voice, and the recipes that produced each asset | [`prsn/`](prsn) ([jaredzimmerman/prsn](https://github.com/jaredzimmerman/prsn)) |
| `.prsncap` | A write-once capture file: the camera, depth, motion and audio streams from one capture session that `.prsn` assets are derived from | specified in [`prsn/spec/prsncap.md`](prsn/spec/prsncap.md) |

Each format lives in its own repository and is included here as a git submodule.

## Getting the formats

```sh
git clone --recurse-submodules https://github.com/jaredzimmerman/digitaltwins.git
```

If you already cloned without submodules:

```sh
git submodule update --init
```

## Status

Draft. The specifications may still change before a 1.x release; see each format's README.

## Licence

Apache License 2.0. See [LICENSE](LICENSE).
