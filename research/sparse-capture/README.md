# Debug capture isolation

`SparseCapture.m` is only in `ReverseCADSparseResearch`. The normal target does not
compile or link it. The file requires both `DEBUG` and `SPARSE_RESEARCH`; the build
script also refuses non-Debug and archive/install build actions. The development
profile used locally belongs to Prelude; see the coordination and build procedure
in [the workflow](../../docs/sparse-reconstruction/README.md).

Hooks use the exact observed runtime type encodings. Missing/changed classes or
encodings remain unavailable; no guessed function signature is called. Callbacks
forward their original arguments unchanged. The normal mode has no black-image
replacement. Existing black-input controls stay in untouched Prelude research.

Physical 1× identification uses source ports/device ID and matching sample PTS,
dimensions and both original active pixel-plane hashes at the ARFrame boundary.
It never assumes a channel number. Camera identity failure prevents that frame
from supplying reconstruction evidence.

There is a 16-slot sensor-write queue, a 96-entry image correspondence ring, a
32 MiB packet cap, an 8-slot motion queue, bounded motion samples, and the enclosing
512 MiB scan budget. Packet and image-journal drops are counted. Packet data/journal
are synced periodically, exact keyframes are committed with checksums, and finish
drains the sensor queue before final checksums. Raw/fused motion capability and drop
counts are recorded. Invalid JSON numbers become null. No packet decoder runs on
the capture callback thread.

Private API presence, packet delivery, identity matching and sensor extrinsics
still require a real phone acceptance run. Successful compilation does not prove
that this OS build exposes those hooks. The current phone is connected and the owner has released the stopped Prelude
session. Recording preservation and prototype installation are pending; no
fresh scan has been verified.
