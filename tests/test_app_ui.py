"""UI-logic tests that do not require a browser or OCR model execution."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import app
from app import (
    DISCLAIMER_TEXT,
    STATUS_SEVERITY,
    analyze_image_payload,
    build_image_payload,
    sorted_findings,
    status_meta,
)


class FakeUploadedFile:
    """Minimal stand-in for an UploadedFile/camera file."""

    def __init__(self, data: bytes, name: str):
        self._data = data
        self.name = name

    def getvalue(self) -> bytes:
        return self._data


def _make_finding(original_text, matched_name, status, reason="reason"):
    return SimpleNamespace(
        original_text=original_text,
        matched_name=matched_name,
        status=status,
        reason=reason,
    )


@pytest.mark.parametrize(
    "status,expected_label,expected_severity",
    [
        ("incompatible", "Incompatible", 0),
        ("depends_on_origin", "Depends on origin", 1),
        ("unrecognized", "Not in the reference", 2),
        ("compatible", "Compatible", 4),
    ],
)
def test_status_to_label_and_severity_mapping(status, expected_label, expected_severity):
    assert status_meta(status)[0] == expected_label
    assert STATUS_SEVERITY[status] == expected_severity


def test_upload_and_camera_payloads_have_same_shape_and_bytes():
    data = b"same-image-bytes"
    upload_payload = build_image_payload(
        "upload", uploaded_file=FakeUploadedFile(data, "label.jpg")
    )
    camera_payload = build_image_payload(
        "camera", camera_file=FakeUploadedFile(data, "camera_input.jpg")
    )

    assert upload_payload["ok"] is True
    assert camera_payload["ok"] is True
    assert upload_payload["bytes"] == camera_payload["bytes"] == data
    assert set(upload_payload) == set(camera_payload)


def test_both_input_sources_call_the_same_analysis_function(monkeypatch):
    calls = []

    def fake_run_label_analysis(image_bytes, image_name, settings):
        calls.append((image_bytes, image_name, settings))
        return {"analysis": "fake"}

    monkeypatch.setattr(app, "run_label_analysis", fake_run_label_analysis)
    settings = {"fast_mode": True, "preprocessing": True}

    upload_payload = {
        "ok": True,
        "bytes": b"image",
        "name": "upload.jpg",
    }
    camera_payload = {
        "ok": True,
        "bytes": b"image",
        "name": "camera.jpg",
    }

    analyze_image_payload(upload_payload, settings)
    analyze_image_payload(camera_payload, settings)

    assert calls == [
        (b"image", "upload.jpg", settings),
        (b"image", "camera.jpg", settings),
    ]


def test_empty_upload_and_no_camera_messages():
    upload_payload = build_image_payload("upload")
    camera_payload = build_image_payload("camera")

    assert upload_payload["ok"] is False
    assert camera_payload["ok"] is False
    assert "Upload" in upload_payload["message"]
    assert "No photo" in camera_payload["message"]
    assert "camera" in camera_payload["message"].lower()


def test_findings_are_sorted_by_requested_severity():
    report = SimpleNamespace(
        findings=[
            _make_finding("A", "A", "compatible"),
            _make_finding("B", "B", "depends_on_origin"),
            _make_finding("C", "C", "incompatible"),
            _make_finding("D", "D", "unrecognized"),
        ]
    )

    rows = sorted_findings([report])
    statuses = [finding.status for _, finding in rows]
    assert statuses == [
        "incompatible",
        "depends_on_origin",
        "unrecognized",
        "compatible",
    ]


def test_apptest_empty_state_and_camera_tab(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("APP_TEST_SKIP_OCR", "1")
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    at = AppTest.from_file(app_path, default_timeout=60)
    at.run()

    assert any("Halal Label Checker" in title.value for title in at.title)
    assert any(DISCLAIMER_TEXT in item.value for item in at.markdown)
    assert at.radio(key="input_source").value == "upload"

    at.radio(key="input_source").set_value("camera").run()
    assert any("close-up" in item.value.lower() for item in at.info)
    assert any("no photo" in item.value.lower() for item in at.markdown)
