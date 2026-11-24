"""
PaddleOCR backend for Halal Label Checker (PaddleOCR 3.x API only).
"""

import os
import time
import logging
from typing import List, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Paddle/torch DLL conflict on Windows: import torch first
try:
    import torch  # noqa: F401
except ImportError:
    pass

# Disable model source check to avoid slow downloads
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

from ..base import OCREngine, OCRError


# PaddleOCR 3.x recognition model names per language.
# Arabic and Latin (French) use dedicated PP-OCRv5 multilingual models.
RECOGNITION_MODELS = {
    "ar": "arabic_PP-OCRv5_mobile_rec",   # Arabic
    "fr": "latin_PP-OCRv5_mobile_rec",    # French / Latin script (keeps accents)
    "latin": "latin_PP-OCRv5_mobile_rec", # Latin script
    "en": "en_PP-OCRv5_mobile_rec",       # English
    "zh": "PP-OCRv6_medium_rec",          # Chinese (Traditional + Simplified; v5 mobile turned 櫚 into 榈)
}

# Detection model (shared across languages)
DETECTION_MODEL = "PP-OCRv5_mobile_det"

# Longest image side allowed before OCR (phone photos are ~3840 px)
DEFAULT_MAX_IMAGE_SIZE = 1600


class PaddleOCREngine(OCREngine):
    """
    PaddleOCR 3.x implementation of OCREngine.

    Uses PP-OCRv5 models with per-language recognition models.
    Caches one PaddleOCR instance per language (loading is slow).

    Only PaddleOCR 3.x constructor arguments are used:
        text_detection_model_name, text_recognition_model_name,
        enable_mkldnn, use_doc_orientation_classify,
        use_doc_unwarping, use_textline_orientation
    """

    def __init__(
        self,
        max_image_size: int = DEFAULT_MAX_IMAGE_SIZE,
        text_det_limit_type: Optional[str] = None,
        text_det_limit_side_len: Optional[int] = None,
        cpu_threads: Optional[int] = None,
    ):
        """
        Args:
            max_image_size: Longest side limit (px) applied before OCR.
            text_det_limit_type: "min" or "max" — which side the det limit
                applies to (PaddleOCR 3.x pipeline option).
            text_det_limit_side_len: Detection side length limit in px.
            cpu_threads: Number of CPU threads for inference.
        """
        self.max_image_size = max_image_size
        self.text_det_limit_type = text_det_limit_type
        self.text_det_limit_side_len = text_det_limit_side_len
        self.cpu_threads = cpu_threads
        # Crops per recognition call. 0 keeps one call for the whole image
        # (default); FAST_MODE sets a positive value so a big page does not
        # pad every crop to the widest line on the page at once.
        self.recognition_batch_size = 0
        self._engines: Dict[str, object] = {}
        self._recognizers: Dict[str, object] = {}
        self._detector = None
        self._load_times: Dict[str, float] = {}

    @property
    def name(self) -> str:
        return "PaddleOCR"

    @property
    def supported_languages(self) -> List[str]:
        return list(RECOGNITION_MODELS.keys())

    def is_available(self) -> bool:
        """Check if PaddleOCR 3.x is installed."""
        try:
            import paddleocr
            return hasattr(paddleocr.PaddleOCR, "predict")
        except ImportError:
            return False

    def get_load_time(self, language: str) -> float:
        return self._load_times.get(language, 0.0)

    def _get_engine(self, language: str):
        """Get or create (and cache) the PaddleOCR instance for a language."""
        if language in self._engines:
            return self._engines[language]

        try:
            from paddleocr import PaddleOCR
        except ImportError as e:
            raise OCRError(
                "PaddleOCR is not installed. Install with: "
                "pip install paddlepaddle==3.3.1 paddleocr==3.7.0"
            ) from e

        rec_model = RECOGNITION_MODELS.get(language)
        if rec_model is None:
            raise OCRError(f"Unsupported language for PaddleOCR: {language}")

        logger.info("Loading PaddleOCR engine for %s (model: %s)", language, rec_model)
        start = time.time()
        try:
            kwargs = dict(
                text_detection_model_name=DETECTION_MODEL,
                text_recognition_model_name=rec_model,
                enable_mkldnn=False,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
            if self.text_det_limit_type is not None:
                kwargs["text_det_limit_type"] = self.text_det_limit_type
            if self.text_det_limit_side_len is not None:
                kwargs["text_det_limit_side_len"] = self.text_det_limit_side_len
            if self.cpu_threads is not None:
                kwargs["cpu_threads"] = self.cpu_threads
            engine = PaddleOCR(**kwargs)
        except Exception as e:
            raise OCRError(
                f"Failed to initialize PaddleOCR for language '{language}' "
                f"(model '{rec_model}'): {type(e).__name__}: {e}"
            ) from e

        load_time = time.time() - start
        self._load_times[language] = load_time
        self._engines[language] = engine
        logger.info("PaddleOCR engine for %s loaded in %.2fs", language, load_time)
        return engine

    def _resize_image(self, image: np.ndarray) -> np.ndarray:
        """Downscale so the longest side is <= max_image_size (aspect preserved)."""
        height, width = image.shape[:2]
        longest = max(height, width)
        if longest <= self.max_image_size:
            return image

        import cv2
        scale = self.max_image_size / float(longest)
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        logger.info("Resizing image from %dx%d to %dx%d", width, height, *new_size)
        return cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)

    def _to_bgr_array(self, image) -> np.ndarray:
        """Normalize PIL/ndarray input to a 3-channel BGR uint8 array."""
        import cv2

        if hasattr(image, "convert"):
            image = np.array(image)

        if image.dtype != np.uint8:
            image = np.clip(image, 0, 255).astype(np.uint8)

        if image.ndim == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if image.shape[2] == 4:
            image = image[:, :, :3]

        # PIL/numpy input is RGB; PaddleOCR expects BGR
        return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    def _get_detector(self):
        """Get or create the shared text-detection pipeline."""
        if self._detector is not None:
            return self._detector

        try:
            from paddleocr import TextDetection
        except ImportError as e:
            raise OCRError(
                "PaddleOCR is not installed. Install with: "
                "pip install paddlepaddle==3.3.1 paddleocr==3.7.0"
            ) from e

        kwargs = dict(
            model_name=DETECTION_MODEL,
            device="cpu",
            enable_mkldnn=False,
        )
        # Detection runs on the already-resized image, so the pipeline limit
        # must not shrink it further.
        kwargs["limit_side_len"] = self.text_det_limit_side_len or self.max_image_size
        kwargs["limit_type"] = self.text_det_limit_type or "max"
        try:
            self._detector = TextDetection(**kwargs)
        except Exception as e:
            raise OCRError(
                f"Failed to initialize PaddleOCR text detection "
                f"(model '{DETECTION_MODEL}'): {type(e).__name__}: {e}"
            ) from e
        logger.info("PaddleOCR text detector loaded (model: %s)", DETECTION_MODEL)
        return self._detector

    def _get_recognizer(self, language: str):
        """Get or create (and cache) a text-recognition pipeline."""
        if language in self._recognizers:
            return self._recognizers[language]

        rec_model = RECOGNITION_MODELS.get(language)
        if rec_model is None:
            raise OCRError(f"Unsupported language for PaddleOCR: {language}")

        try:
            from paddleocr import TextRecognition
        except ImportError as e:
            raise OCRError(
                "PaddleOCR is not installed. Install with: "
                "pip install paddlepaddle==3.3.1 paddleocr==3.7.0"
            ) from e

        logger.info("Loading PaddleOCR recognizer for %s (model: %s)", language, rec_model)
        try:
            recognizer = TextRecognition(
                model_name=rec_model,
                device="cpu",
                enable_mkldnn=False,
            )
        except Exception as e:
            raise OCRError(
                f"Failed to initialize PaddleOCR recognition for language "
                f"'{language}' (model '{rec_model}'): {type(e).__name__}: {e}"
            ) from e

        self._recognizers[language] = recognizer
        return recognizer

    def detect_polygons(self, image) -> List[np.ndarray]:
        """
        Run text detection ONCE and return 4-corner polygons.

        The same polygons are reused by every recognition model.
        """
        detector = self._get_detector()
        image_bgr = self._to_bgr_array(image)
        image_resized = self._resize_image(image_bgr)

        try:
            raw_result = detector.predict(image_resized)
        except Exception as e:
            raise OCRError(
                f"PaddleOCR text detection failed: {type(e).__name__}: {e}"
            ) from e

        if not raw_result:
            return []
        try:
            polys = raw_result[0]["dt_polys"]
        except (KeyError, TypeError) as e:
            raise OCRError(
                f"Unexpected PaddleOCR detection format: {type(e).__name__}: {e}"
            ) from e

        polygons: List[np.ndarray] = []
        for poly in polys:
            pts = np.asarray(poly, dtype=np.float32)
            if pts.size == 0:
                continue
            polygons.append(pts.reshape(-1, 2))
        return polygons

    @staticmethod
    def _polygon_bbox(polygon) -> List[float]:
        pts = np.asarray(polygon, dtype=float)
        return [
            float(pts[:, 0].min()),
            float(pts[:, 1].min()),
            float(pts[:, 0].max()),
            float(pts[:, 1].max()),
        ]

    def detect_boxes(self, image) -> List[List[float]]:
        """Detect once and return flat [x0, y0, x1, y1] boxes."""
        return [self._polygon_bbox(poly) for poly in self.detect_polygons(image)]

    def detect_polygons_tiled(self, image, overlap: float = 0.12,
                              max_tile_long: int = 1200) -> List[np.ndarray]:
        """
        Detect text on a wide/tall page by splitting it into overlapping tiles.

        The detector clamps the longest side to limit_side_len, so on a very
        wide (or tall) photo every line shrinks and small text is missed. Each
        tile keeps its long side close to the model's native scale. Polygons
        are returned in the full resized-image coordinate space, exactly like
        detect_polygons(), so recognition and callers need no extra mapping.
        """
        image_bgr = self._to_bgr_array(image)
        resized = self._resize_image(image_bgr)
        height, width = resized.shape[:2]
        vertical = height >= width
        long_len = height if vertical else width
        if long_len <= max_tile_long:
            return self.detect_polygons(image)

        tile_len = min(max_tile_long, long_len)
        step = max(1, int(round(tile_len * (1.0 - overlap))))
        spans = []
        start = 0
        while True:
            end = min(start + tile_len, long_len)
            spans.append((start, end))
            if end >= long_len:
                break
            start += step

        polygons: List[np.ndarray] = []
        for start, end in spans:
            if vertical:
                tile = resized[start:end, :]
                offset_x, offset_y = 0, start
            else:
                tile = resized[:, start:end]
                offset_x, offset_y = start, 0
            if tile.shape[0] < 8 or tile.shape[1] < 8:
                continue
            tile_polygons = self._detect_on_array(tile)
            for poly in tile_polygons:
                pts = np.asarray(poly, dtype=np.float32).reshape(-1, 2).copy()
                pts[:, 0] += offset_x
                pts[:, 1] += offset_y
                polygons.append(pts)

        return self._dedupe_polygons(polygons)

    def _detect_on_array(self, image_bgr: np.ndarray) -> List[np.ndarray]:
        """Run the detector on an already prepared BGR array."""
        detector = self._get_detector()
        try:
            raw_result = detector.predict(image_bgr)
        except Exception as e:
            raise OCRError(
                f"PaddleOCR text detection failed: {type(e).__name__}: {e}"
            ) from e
        if not raw_result:
            return []
        try:
            polys = raw_result[0]["dt_polys"]
        except (KeyError, TypeError) as e:
            raise OCRError(
                f"Unexpected PaddleOCR detection format: {type(e).__name__}: {e}"
            ) from e
        polygons: List[np.ndarray] = []
        for poly in polys:
            pts = np.asarray(poly, dtype=np.float32)
            if pts.size == 0:
                continue
            polygons.append(pts.reshape(-1, 2))
        return polygons

    @classmethod
    def _dedupe_polygons(cls, polygons: List[np.ndarray],
                         iou_threshold: float = 0.5) -> List[np.ndarray]:
        """Drop tile-overlap duplicates: the same line detected twice."""
        kept: List[np.ndarray] = []
        kept_boxes: List[List[float]] = []
        for poly in polygons:
            box = cls._polygon_bbox(poly)
            duplicate = False
            for other in kept_boxes:
                ix0, iy0 = max(box[0], other[0]), max(box[1], other[1])
                ix1, iy1 = min(box[2], other[2]), min(box[3], other[3])
                if ix1 <= ix0 or iy1 <= iy0:
                    continue
                inter = (ix1 - ix0) * (iy1 - iy0)
                area_a = (box[2] - box[0]) * (box[3] - box[1])
                area_b = (other[2] - other[0]) * (other[3] - other[1])
                union = area_a + area_b - inter
                if union > 0 and inter / union >= iou_threshold:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(poly)
                kept_boxes.append(box)
        return kept

    def _crop_polygon(self, image: np.ndarray, polygon, padding: int = 0) -> np.ndarray:
        """
        Crop a text line exactly like PaddleX's CropByPolys:
        minAreaRect -> corner sort -> perspective warp, then 90° rotation for
        vertical lines.

        Padding must stay 0: omitted borders change the crop aspect ratio, so
        the recognizer's 48px height normalization shrinks the glyphs. On this
        474x218 label a 2px border turned 16px lines into 20px ones and pushed
        scores from ~0.95 to ~0.5. `BORDER_REPLICATE` already protects edges.
        """
        import cv2

        pts = np.asarray(polygon, dtype=np.int32).reshape(-1, 2)
        if len(pts) < 4:
            x0, y0, x1, y1 = self._polygon_bbox(pts)
            x0, y0 = max(0, int(x0) - padding), max(0, int(y0) - padding)
            x1 = min(image.shape[1], int(x1) + padding)
            y1 = min(image.shape[0], int(y1) + padding)
            return image[y0:y1, x0:x1]

        rect = cv2.minAreaRect(pts)
        points = sorted(list(cv2.boxPoints(rect)), key=lambda point: point[0])

        index_a, index_b, index_c, index_d = 0, 1, 2, 3
        if points[1][1] > points[0][1]:
            index_a, index_d = 0, 1
        else:
            index_a, index_d = 1, 0
        if points[3][1] > points[2][1]:
            index_b, index_c = 2, 3
        else:
            index_b, index_c = 3, 2

        box = np.array(
            [points[index_a], points[index_b], points[index_c], points[index_d]],
            dtype=np.float32,
        )
        width = int(max(
            np.linalg.norm(box[0] - box[1]),
            np.linalg.norm(box[2] - box[3]),
        ))
        height = int(max(
            np.linalg.norm(box[0] - box[3]),
            np.linalg.norm(box[1] - box[2]),
        ))
        width, height = max(width, 2), max(height, 2)

        dst = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
        transform = cv2.getPerspectiveTransform(box, dst)
        crop = cv2.warpPerspective(
            image, transform, (width, height),
            borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_CUBIC,
        )

        # Vertical text lines are rotated 90°, as in the PaddleOCR pipeline
        if crop.shape[0] * 1.0 / max(crop.shape[1], 1) >= 1.5:
            crop = np.rot90(crop)

        if padding > 0 and crop.size > 0:
            crop = cv2.copyMakeBorder(
                crop, padding, padding, padding, padding,
                borderType=cv2.BORDER_REPLICATE,
            )
        return crop

    def _run_recognizer(self, recognizer, crops: List[np.ndarray], language: str) -> List[Dict]:
        """
        Recognize crops, optionally in batches, always returning one dict per crop.

        A single call on a whole page pads every crop to the widest line of the
        page. Batching (recognition_batch_size > 0) sends groups of
        similar-width crops together, which cuts that padding. Results are put
        back in the original crop order, so batching cannot change which text
        belongs to which box.
        """
        if not crops:
            return []

        order = list(range(len(crops)))
        step = self.recognition_batch_size or len(crops)
        if self.recognition_batch_size and len(crops) > self.recognition_batch_size:
            # Widest first: each batch then pads to its own maximum, not the page's.
            order.sort(key=lambda index: -crops[index].shape[1])

        results: List[Optional[Dict]] = [None] * len(crops)
        for start in range(0, len(order), step):
            chunk = order[start:start + step]
            try:
                outputs = recognizer.predict([crops[index] for index in chunk])
            except Exception as e:
                raise OCRError(
                    f"PaddleOCR recognition failed for language '{language}': "
                    f"{type(e).__name__}: {e}"
                ) from e
            if len(outputs) != len(chunk):
                raise OCRError(
                    f"PaddleOCR returned {len(outputs)} recognition results "
                    f"for {len(chunk)} crops (language '{language}')"
                )
            for index, output in zip(chunk, outputs):
                results[index] = {
                    "text": str(output.get("rec_text") or "").strip(),
                    "confidence": float(output.get("rec_score") or 0.0),
                }
        return results

    def recognize_polygons(self, image, polygons: List[np.ndarray], language: str) -> List[Dict]:
        """
        Recognize polygon-line crops (perspective warp + padding) for one model.

        Returns one dict per polygon so the caller keeps the boxes aligned.
        """
        results: List[Dict] = [
            {"text": "", "confidence": 0.0, "bbox": self._polygon_bbox(poly)}
            for poly in polygons
        ]
        if not polygons:
            return results

        recognizer = self._get_recognizer(language)
        image_bgr = self._to_bgr_array(image)
        image_resized = self._resize_image(image_bgr)

        crops: List[np.ndarray] = []
        valid_indices: List[int] = []
        for index, polygon in enumerate(polygons):
            crop = self._crop_polygon(image_resized, polygon)
            if crop is None or crop.size == 0 or crop.shape[0] < 2 or crop.shape[1] < 2:
                continue
            crops.append(crop)
            valid_indices.append(index)

        predictions = self._run_recognizer(recognizer, crops, language)
        for index, prediction in zip(valid_indices, predictions):
            results[index] = {
                "text": prediction["text"],
                "confidence": prediction["confidence"],
                "bbox": self._polygon_bbox(polygons[index]),
            }
        return results

    def recognize_boxes(self, image, boxes: List[List[float]], language: str) -> List[Dict]:
        """Recognize flat boxes with one language model (axis-aligned fallback)."""
        results: List[Dict] = [
            {"text": "", "confidence": 0.0, "bbox": list(box)} for box in boxes
        ]
        if not boxes:
            return results

        recognizer = self._get_recognizer(language)
        image_bgr = self._to_bgr_array(image)
        image_resized = self._resize_image(image_bgr)

        crops: List[np.ndarray] = []
        valid_indices: List[int] = []
        for index, box in enumerate(boxes):
            x0, y0, x1, y1 = [int(round(float(value))) for value in box[:4]]
            pad = 4
            x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
            x1 = min(image_resized.shape[1], x1 + pad)
            y1 = min(image_resized.shape[0], y1 + pad)
            if x1 <= x0 or y1 <= y0:
                continue
            crop = image_resized[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            crops.append(crop)
            valid_indices.append(index)

        predictions = self._run_recognizer(recognizer, crops, language)
        for index, prediction in zip(valid_indices, predictions):
            results[index] = {
                "text": prediction["text"],
                "confidence": prediction["confidence"],
                "bbox": list(boxes[index]),
            }
        return results

    def recognize(self, image, language: str) -> List[Dict]:
        """
        Run OCR for one language. Raises OCRError on failure (never silently
        returns an empty list because of an exception).
        """
        engine = self._get_engine(language)
        image_bgr = self._to_bgr_array(image)
        image_resized = self._resize_image(image_bgr)

        try:
            raw_result = engine.predict(image_resized)
        except Exception as e:
            raise OCRError(
                f"PaddleOCR recognition failed for language '{language}': "
                f"{type(e).__name__}: {e}"
            ) from e

        results: List[Dict] = []
        if not raw_result:
            return results

        for res in raw_result:
            # PaddleOCR 3.x returns a result object supporting dict-like access
            try:
                texts = res["rec_texts"]
                scores = res["rec_scores"]
            except (KeyError, TypeError) as e:
                raise OCRError(
                    f"Unexpected PaddleOCR result format for language '{language}': {e}"
                ) from e

            boxes = None
            for key in ("rec_boxes", "dt_polys", "rec_polys"):
                try:
                    boxes = res[key]
                    break
                except (KeyError, TypeError):
                    continue

            for i, text in enumerate(texts):
                if not text or not str(text).strip():
                    continue
                confidence = float(scores[i]) if i < len(scores) else 0.0
                bbox = []
                if boxes is not None and i < len(boxes):
                    raw_box = boxes[i]
                    bbox = raw_box.tolist() if hasattr(raw_box, "tolist") else list(raw_box)
                results.append({
                    "text": str(text).strip(),
                    "confidence": confidence,
                    "bbox": bbox,
                })

        return results

    def close(self):
        self._engines.clear()
        self._recognizers.clear()
        self._detector = None
        self._load_times.clear()
