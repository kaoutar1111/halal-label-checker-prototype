"""
Image preprocessing module for Halal Label Checker.
Applies OpenCV-based preprocessing to improve OCR accuracy.
"""

import numpy as np
from PIL import Image
from typing import Tuple, Optional
import cv2
import logging

logger = logging.getLogger(__name__)


class ImagePreprocessor:
    """
    Image preprocessing pipeline for OCR optimization.
    """
    
    def __init__(self, 
                 apply_grayscale: bool = True,
                 apply_contrast: bool = True,
                 apply_denoise: bool = True,
                 apply_deskew: bool = True):
        """
        Initialize preprocessor with configuration.
        
        Args:
            apply_grayscale: Convert to grayscale
            apply_contrast: Apply contrast enhancement
            apply_denoise: Apply denoising
            apply_deskew: Apply deskewing
        """
        self.apply_grayscale = apply_grayscale
        self.apply_contrast = apply_contrast
        self.apply_denoise = apply_denoise
        self.apply_deskew = apply_deskew
    
    def to_numpy(self, image: Image.Image) -> np.ndarray:
        """Convert PIL Image to numpy array."""
        return np.array(image)
    
    def to_pil(self, array: np.ndarray) -> Image.Image:
        """Convert numpy array to PIL Image."""
        # Ensure correct dtype and range
        if array.dtype != np.uint8:
            array = np.clip(array, 0, 255).astype(np.uint8)
        return Image.fromarray(array)
    
    def to_grayscale(self, image: np.ndarray) -> np.ndarray:
        """Convert image to grayscale."""
        if len(image.shape) == 3:
            # Use weighted grayscale conversion (ITU-R BT.601)
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
            return gray
        return image
    
    def apply_clahe(self, image: np.ndarray, clip_limit: float = 2.0, tile_size: Tuple[int, int] = (8, 8)) -> np.ndarray:
        """
        Apply Contrast Limited Adaptive Histogram Equalization.
        Improves text readability in varying lighting conditions.
        """
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_size)
        return clahe.apply(image)
    
    def enhance_contrast(self, image: np.ndarray) -> np.ndarray:
        """Apply contrast enhancement using CLAHE."""
        if len(image.shape) == 3:
            gray = self.to_grayscale(image)
        else:
            gray = image
        
        enhanced = self.apply_clahe(gray)
        
        # Convert back to 3-channel if original was color
        if len(image.shape) == 3:
            enhanced = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2RGB)
        
        return enhanced
    
    def denoise(self, image: np.ndarray, strength: int = 10) -> np.ndarray:
        """
        Apply denoising to reduce noise.
        
        Args:
            image: Input image array
            strength: Denoising strength (higher = more denoising)
        """
        if len(image.shape) == 3:
            # FastNLMeansDenoisingColored
            return cv2.fastNlMeansDenoisingColored(image, None, strength, strength, 7, 21)
        else:
            return cv2.fastNlMeansDenoising(image, None, strength, 7, 21)
    
    def detect_edges(self, image: np.ndarray) -> np.ndarray:
        """Detect edges using Canny edge detector."""
        if len(image.shape) == 3:
            gray = self.to_grayscale(image)
        else:
            gray = image
        
        return cv2.Canny(gray, 50, 150)
    
    def find_contours(self, edges: np.ndarray) -> list:
        """Find contours in edge-detected image."""
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return contours
    
    def calculate_angle(self, contour: np.ndarray) -> float:
        """Calculate rotation angle from contour using minAreaRect."""
        try:
            rect = cv2.minAreaRect(contour)
            angle = rect[-1]
            return angle
        except:
            return 0.0
    
    def deskew(self, image: np.ndarray) -> np.ndarray:
        """
        Detect and correct image skew.
        
        Args:
            image: Input image
        
        Returns:
            Deskewed image
        """
        if len(image.shape) == 3:
            gray = self.to_grayscale(image)
        else:
            gray = image
        
        # Threshold to get binary image
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        # Find edges
        edges = cv2.Canny(thresh, 50, 150)
        
        # Find lines using Hough transform
        lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=100)
        
        if lines is None or len(lines) == 0:
            return image
        
        # Calculate average angle
        angles = []
        for line in lines[:20]:  # Consider only first 20 lines
            rho, theta = line[0]
            # Convert theta to angle in degrees
            angle = (theta * 180 / np.pi) - 90
            angles.append(angle)
        
        avg_angle = np.median(angles)
        
        # Only rotate if angle is significant
        if abs(avg_angle) < 0.5:
            return image
        
        # Rotate the image
        height, width = gray.shape[:2]
        center = (width // 2, height // 2)
        
        rotation_matrix = cv2.getRotationMatrix2D(center, avg_angle, 1.0)
        
        if len(image.shape) == 3:
            return cv2.warpAffine(image, rotation_matrix, (width, height), 
                                   flags=cv2.INTER_CUBIC, 
                                   borderMode=cv2.BORDER_REPLICATE)
        else:
            return cv2.warpAffine(image, rotation_matrix, (width, height),
                                   flags=cv2.INTER_CUBIC,
                                   borderMode=cv2.BORDER_REPLICATE)
    
    def resize_for_ocr(self, image: np.ndarray, min_size: int = 800, max_size: int = 2000) -> np.ndarray:
        """
        Resize image to optimal size for OCR.
        
        Args:
            image: Input image
            min_size: Minimum dimension size
            max_size: Maximum dimension size
        
        Returns:
            Resized image
        """
        height, width = image.shape[:2]
        
        # Calculate scaling factor
        if min(height, width) < min_size:
            scale = min_size / min(height, width)
        elif max(height, width) > max_size:
            scale = max_size / max(height, width)
        else:
            return image
        
        new_width = int(width * scale)
        new_height = int(height * scale)
        
        return cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
    
    def preprocess(self, image: Image.Image, resize: bool = True) -> Image.Image:
        """
        Apply full preprocessing pipeline.
        
        Args:
            image: PIL Image to preprocess
            resize: Whether to resize for optimal OCR
        
        Returns:
            Preprocessed PIL Image
        """
        # Convert to numpy
        img_array = self.to_numpy(image)
        
        # Resize if needed
        if resize:
            img_array = self.resize_for_ocr(img_array)
        
        # Apply preprocessing steps
        if self.apply_grayscale:
            img_array = self.to_grayscale(img_array)
        
        if self.apply_contrast:
            img_array = self.enhance_contrast(img_array)
        
        if self.apply_denoise:
            img_array = self.denoise(img_array)
        
        if self.apply_deskew:
            img_array = self.deskew(img_array)
        
        return self.to_pil(img_array)


# Convenience function
def preprocess_image(image: Image.Image, 
                     grayscale: bool = True,
                     contrast: bool = True,
                     denoise: bool = True,
                     deskew: bool = True) -> Image.Image:
    """
    Apply preprocessing to an image.
    
    Args:
        image: PIL Image
        grayscale: Convert to grayscale
        contrast: Enhance contrast
        denoise: Apply denoising
        deskew: Correct skew
    
    Returns:
        Preprocessed PIL Image
    """
    preprocessor = ImagePreprocessor(
        apply_grayscale=grayscale,
        apply_contrast=contrast,
        apply_denoise=denoise,
        apply_deskew=deskew
    )
    return preprocessor.preprocess(image)
