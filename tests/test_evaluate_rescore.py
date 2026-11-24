import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_rescore_uses_stored_ocr_without_running_ocr(tmp_path):
    eval_dir = tmp_path / "eval"
    image = eval_dir / "en" / "01.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"not read by --rescore")
    image.with_suffix(".truth.json").write_text(json.dumps({
        "ingredients_text": "sugar, salt",
    }), encoding="utf-8")

    store = eval_dir / "ocr_outputs" / "off" / "en" / "01.json"
    store.parent.mkdir(parents=True)
    store.write_text(json.dumps({
        "results": [
            {"text": "INGREDIENTS", "confidence": 0.99, "language": "en",
             "bbox": [[0, 0], [100, 0], [100, 20], [0, 20]]},
            {"text": "sugar, salt", "confidence": 0.99, "language": "en",
             "bbox": [[0, 30], [100, 30], [100, 50], [0, 50]]},
        ],
        "unreadable": [],
        "diagnostics": {"strategy": "stored_test", "blocks_detected": 2,
                        "blocks_kept": 2, "retry": {}},
    }), encoding="utf-8")

    csv_path = tmp_path / "results.csv"
    report_path = tmp_path / "report.md"
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "evaluate.py"),
         "--eval-dir", str(eval_dir), "--rescore", "--fast-mode", "off",
         "--csv", str(csv_path), "--report", str(report_path)],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stdout + completed.stderr

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["cer_content"] == "0.0000"
    assert rows[0]["verdict_ok"] == "yes"
    assert rows[0]["strategy"] == "rescore:stored_test"
    assert rows[0]["time_warm_s"] == "0.00"
    assert "rescore:stored_test" in report_path.read_text(encoding="utf-8")


def test_expected_values_are_computed_from_the_truth_text():
    from scripts import evaluate

    matcher = evaluate.IngredientMatcher()
    generator = evaluate.VerdictGenerator()

    verdict, flags = evaluate.expected_from_truth("sugar, salt", matcher, generator)
    assert verdict == evaluate.VERDICT_CLEAR
    assert flags == []

    verdict, flags = evaluate.expected_from_truth(
        "sugar, xyzabc", matcher, generator)
    assert verdict == evaluate.VERDICT_TO_VERIFY  # unrecognized forces review
    assert flags == []

    verdict, flags = evaluate.expected_from_truth(
        "sugar, 食用香精", matcher, generator)
    assert verdict == evaluate.VERDICT_TO_VERIFY
    assert flags


def test_normal_run_stores_blocks_used_by_rescore(tmp_path):
    from PIL import Image
    from scripts import evaluate

    eval_dir = tmp_path / "eval"
    image_path = eval_dir / "en" / "01.jpg"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (100, 60), "white").save(image_path)
    truth_path = image_path.with_suffix(".truth.json")
    truth_path.write_text(json.dumps({
        "ingredients_text": "sugar, salt",
    }), encoding="utf-8")
    blocks = [
        evaluate.OCRResult("INGREDIENTS", 0.99, "en",
                           [[0, 0], [100, 0], [100, 20], [0, 20]]),
        evaluate.OCRResult("sugar, salt", 0.99, "en",
                           [[0, 30], [100, 30], [100, 50], [0, 50]]),
    ]

    class FakeOCR:
        last_dropped = []
        last_uncertain = []
        last_strategy = "fake_ocr"
        last_blocks_detected = len(blocks)
        last_retry = {}

        def process_image(self, image, auto=True):
            return blocks

    matcher, generator = evaluate.IngredientMatcher(), evaluate.VerdictGenerator()
    entries_by_id = {entry["id"]: entry for entry in matcher.entries}
    images = [("en", image_path, truth_path)]
    normal_rows, _ = evaluate.collect_mode(
        FakeOCR(), matcher, generator, entries_by_id, images, False, eval_dir)

    store = evaluate.ocr_store_path(eval_dir, False, image_path)
    payload = json.loads(store.read_text(encoding="utf-8"))
    assert [item["text"] for item in payload["results"]] == [
        "INGREDIENTS", "sugar, salt"]
    assert payload["diagnostics"]["strategy"] == "fake_ocr"

    rescore_rows, _ = evaluate.collect_mode(
        None, matcher, generator, entries_by_id, images, False, eval_dir,
        rescore=True)
    assert rescore_rows[0]["cer_content"] == normal_rows[0]["cer_content"] == "0.0000"
    assert rescore_rows[0]["verdict_ok"] == normal_rows[0]["verdict_ok"] == "yes"
    assert rescore_rows[0]["strategy"] == "rescore:fake_ocr"
    assert rescore_rows[0]["time_warm_s"] == "0.00"
