"""Provider adapter tests substitute only external HTTP responses."""
import json
import httpx
import pytest
from reversecad.reasoning import propose, validate_intent, RepairIntent, ReasoningError


def request(**kw):
    return {"family":"bridge_handle","parameters":{"span":80},"attachment_method":"fasteners","mode":"manual",**kw}


def intent(**kw):
    return {"schema_version":1,"family":"bridge_handle","parameters":[{"name":"span","value":80,"source":"manual","measurement_id":None}],"measurement_refs":[],"attachment_method":"fasteners","questions":[],"explanation":"Handle for selected contacts","requested_validation":["solid","mesh"],**kw}


def response(payload=None, **kw):
    return {"status":"completed","id":"fixture-response","output":[{"type":"message","content":[{"type":"output_text","text":json.dumps(payload or intent())}]}],**kw}


def test_manual_and_fixture_are_distinguished(tmp_path):
    assert propose(tmp_path, {}, request())["provider_status"] == "manual_no_provider"
    assert propose(tmp_path, {}, request(mode="fixture"))["provider_status"] == "offline_fixture"


def test_missing_key_is_explicit(tmp_path,monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY",raising=False)
    with pytest.raises(ReasoningError, match="server-side") as err:
        propose(tmp_path,{},request(mode="live",provider_consent=True))
    assert err.value.code == "provider_key_missing"


def test_attachment_cannot_change():
    with pytest.raises(ReasoningError,match="attachment"):
        validate_intent(intent(attachment_method="glue"),{},request())


def test_unknown_observation_rejected():
    with pytest.raises(ReasoningError,match="unknown measurement"):
        validate_intent(intent(measurement_refs=["invented"]),{},request())


def test_critical_confirmed_dimension_preserved():
    evidence={"measurements":[{"id":"m1","name":"span","unit":"mm","value":83,"source":"manual","confirmed":True,"critical":True}]}
    with pytest.raises(ReasoningError,match="Keep confirmed span"):
        validate_intent(intent(),evidence,request())


def test_inferred_dimension_cannot_claim_measured():
    evidence={"measurements":[{"id":"m1","name":"span","unit":"mm","value":80,"source":"design_inference"}]}
    p=intent(parameters=[{"name":"span","value":80,"source":"measurement","measurement_id":"m1"}],measurement_refs=["m1"])
    with pytest.raises(ReasoningError,match="assumption"):
        validate_intent(p,evidence,request())


def test_parameter_bounds_and_invalid_code():
    with pytest.raises(ReasoningError,match="bounds"):
        validate_intent(intent(parameters=[{"name":"span","value":8000,"source":"manual","measurement_id":None}]),{},request(parameters={"span":8000}))
    with pytest.raises(ReasoningError,match="Unsupported parameter"):
        validate_intent(intent(parameters=[{"name":"__import__","value":1,"source":"manual","measurement_id":None}]),{},request())


def test_actual_responses_shape_and_images(tmp_path,monkeypatch):
    from PIL import Image
    monkeypatch.setenv("OPENAI_API_KEY","test-key-not-real")
    (tmp_path / "rgb").mkdir()
    Image.new("RGB",(20,20),(127,34,19)).save(tmp_path / "rgb/a.jpg")
    (tmp_path / "frames.jsonl").write_text(json.dumps({"rgb_path":"rgb/a.jpg"})+'\n')
    calls=[]
    def handler(req):
        body=json.loads(req.content)
        calls.append(body)
        assert str(req.url)=="https://api.openai.com/v1/responses"
        assert body["text"]["format"]["strict"] is True
        assert body["reasoning"]["effort"]=="high"
        assert body["store"] is False
        assert body["input"][0]["content"][1]["type"]=="input_image"
        return httpx.Response(200,json=response())
    result=propose(tmp_path,{},request(mode="live",provider_consent=True),transport=httpx.MockTransport(handler))
    assert result["provider_status"]=="live"  # Mock HTTP only; not live-provider evidence.
    assert result["attempts"]==1 and len(calls)==1


@pytest.mark.parametrize("body,code",[
    (response(status="incomplete"),"provider_incomplete"),
    ({"status":"completed","output":[{"content":[{"type":"refusal"}]}]},"provider_refusal")])
def test_provider_refusal_incomplete(tmp_path,monkeypatch,body,code):
    monkeypatch.setenv("OPENAI_API_KEY","test-key-not-real")
    with pytest.raises(ReasoningError) as err:
        propose(tmp_path,{},request(mode="live",provider_consent=True),transport=httpx.MockTransport(lambda req:httpx.Response(200,json=body)))
    assert err.value.code==code


@pytest.mark.parametrize("status",[401,404,429,500])
def test_provider_http_errors_are_bounded(tmp_path,monkeypatch,status):
    monkeypatch.setenv("OPENAI_API_KEY","test-key-not-real")
    calls=[]
    def handler(req):
        calls.append(req)
        return httpx.Response(status,json={"error":"do not echo provider internals or secrets"})
    with pytest.raises(ReasoningError) as err:
        propose(tmp_path,{},request(mode="live",provider_consent=True),transport=httpx.MockTransport(handler))
    assert err.value.code==f"provider_http_{status}" and len(calls)==1


def test_invalid_intent_max_three_attempts(tmp_path,monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","test-key-not-real")
    calls=[]
    def handler(req):
        calls.append(req)
        return httpx.Response(200,json=response(payload={"bogus":True}))
    with pytest.raises(ReasoningError) as err:
        propose(tmp_path,{},request(mode="live",provider_consent=True),transport=httpx.MockTransport(handler))
    assert err.value.code=="provider_invalid_intent" and len(calls)==3


def test_network_timeout(tmp_path,monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","test-key-not-real")
    def handler(req): raise httpx.ReadTimeout("private diagnostics")
    with pytest.raises(ReasoningError) as err:
        propose(tmp_path,{},request(mode="live",provider_consent=True),transport=httpx.MockTransport(handler))
    assert err.value.code=="provider_network_error"


def test_live_consent_and_ultra_rejected(tmp_path,monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","test-key-not-real")
    with pytest.raises(ReasoningError) as err: propose(tmp_path,{},request(mode="live"))
    assert err.value.code=="provider_consent_required"
    monkeypatch.setenv("REVERSECAD_OPENAI_REASONING","ultra")
    with pytest.raises(ReasoningError) as err: propose(tmp_path,{},request(mode="live",provider_consent=True))
    assert err.value.code=="invalid_reasoning_effort"


def test_default_design_parameters_are_not_measured(tmp_path):
    result=propose(tmp_path,{},request())
    assert result["provenance"]["span"]["source"]=="design_inference"
    measured={"measurements":[{"id":"m","name":"span","value":80,"unit":"mm","source":"manual","critical":True,"confirmed":True}]}
    result=propose(tmp_path,measured,request())
    assert result["provenance"]["span"]["source"]=="measurement"
    assert result["measurement_refs"]==["m"]


def test_confirmed_upper_cup_radius_is_bound():
    p=intent(family="cup_handle",attachment_method="saddle",parameters=[{"name":"cup_radius_top","value":41,"source":"manual","measurement_id":None}])
    evidence={"measurements":[{"id":"top","name":"cup_radius_top","value":42,"unit":"mm","source":"manual","confirmed":True,"critical":True}]}
    with pytest.raises(ReasoningError,match="Keep confirmed cup_radius_top"):
        validate_intent(p,evidence,request(family="cup_handle",attachment_method="saddle",parameters={"cup_radius_top":41}))


def test_acknowledged_unconfirmed_prototype_preserves_uncertainty(tmp_path):
    evidence={"measurements":[{"id":"span_fit","name":"span","value":80,"unit":"mm","source":"depth_fit","critical":True,"confirmed":False}]}
    blocked=propose(tmp_path,evidence,request())
    assert blocked["questions"]
    prototype=propose(tmp_path,evidence,request(acknowledge_uncertainty=True))
    assert prototype["questions"]==[] and prototype["unresolved_measurements"]
    assert prototype["provenance"]["span"]["measurement_id"]=="span_fit"


def test_rendered_scan_evidence_is_real_bounded_projection(tmp_path):
    from reversecad.reasoning import _rendered_scan_content
    from PIL import Image
    import base64, io
    preview=tmp_path/"preview.json"
    preview.write_text(json.dumps({"unit":"mm","vertices":[[0,0,0],[40,0,0],[0,30,0],[0,0,20]],"triangles":[]}))
    result=_rendered_scan_content(preview)
    image=Image.open(io.BytesIO(base64.b64decode(result[0]["image_url"].split(",",1)[1])))
    assert image.size==(768,768)
    assert len(image.getcolors(768*768))>10
