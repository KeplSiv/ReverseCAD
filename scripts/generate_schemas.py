#!/usr/bin/env python3
"""Export versioned schemas directly from the validated production contracts."""
import json
from pathlib import Path
from reversecad.contracts import CaptureFrame, ScanManifest, Annotations, RepairRequest, CandidateRequest, ReconstructionRequest
from reversecad.reasoning import RepairIntent
root=Path(__file__).resolve().parents[1]/"schemas"
for name,model in [("capture-frame-v1",CaptureFrame),("scan-manifest-v1",ScanManifest),("annotations-v1",Annotations),("repair-request-v1",RepairRequest),("repair-intent-v1",RepairIntent),("candidate-request-v1",CandidateRequest),("reconstruction-request-v1",ReconstructionRequest)]:
    (root/(name.replace("-v1", ".v1.schema")+".json")).write_text(json.dumps(model.model_json_schema(),indent=2)+"\n")
print("Exported 7 production schemas")
