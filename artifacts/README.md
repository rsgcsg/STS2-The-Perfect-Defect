# Artifact workspace

Generated checkpoints, model files, feature caches, and raw reports are ignored and should
live locally or in an approved artifact store.

The repository tracks only small artifact manifests containing:

- experiment/source/data/model identities;
- relative file names, byte sizes, and SHA-256 digests;
- compatibility scope and benchmark summary;
- non-claims and reproduction instructions.

Never commit Qwen weights, STS2 files, secrets, private runtime traces, or large generated
features.
