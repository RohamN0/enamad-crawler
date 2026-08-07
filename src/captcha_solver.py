from scipy import ndimage
from pathlib import Path
from PIL import Image
import numpy as np
import ddddocr, cv2, io

class CaptchaSolver:
    def __init__(self):
        self.ocr = ddddocr.DdddOcr(show_ad=False)

    def _load_image(self, image_input):
        if isinstance(image_input, (str, Path)):
            img = Image.open(image_input).convert("L")
        elif isinstance(image_input, bytes):
            img = Image.open(io.BytesIO(image_input)).convert("L")
        else:
            raise ValueError("Input must be a file path or bytes.")
        return np.array(img)

    def _preprocess(self, gray_img):
        # Sharpen
        blurred = cv2.GaussianBlur(gray_img, (0, 0), 1.0)
        sharpened = cv2.addWeighted(gray_img, 1.5, blurred, -0.5, 0)
        gray = np.clip(sharpened, 0, 255).astype(np.uint8)

        # Binarize
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Find and Isolate Main Text Band
        h, w = binary.shape
        row_counts = np.sum(binary > 0, axis=1).astype(float)
        
        # Smooth row counts
        kernel = np.ones(3) / 3
        row_counts = np.convolve(row_counts, kernel, mode='same')
        
        row_thresh = np.mean(row_counts[row_counts > 0]) * 0.3 if np.any(row_counts > 0) else 0
        text_mask = row_counts > row_thresh
        
        runs = []
        start, in_run = 0, False
        for i in range(len(text_mask)):
            if text_mask[i] and not in_run:
                start, in_run = i, True
            elif not text_mask[i] and in_run:
                runs.append((start, i - 1))
                in_run = False
        
        if runs:
            best_run = max(runs, key=lambda r: np.sum(row_counts[r[0]:r[1]+1]))
            y_start, y_end = max(0, best_run[0] - 2), min(h - 1, best_run[1] + 2)
            # Mask areas outside the band
            temp_binary = np.zeros_like(binary)
            temp_binary[y_start:y_end + 1, :] = binary[y_start:y_end + 1, :]
            binary = temp_binary

        # Remove Noise
        labeled, num_features = ndimage.label(binary)
        binary_clean = np.zeros_like(binary)
        for i in range(1, num_features + 1):
            component = labeled == i
            if np.sum(component) >= 4: # min_size
                binary_clean[component] = 255

        # Morphological Ops
        kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 2))
        binary_dilated = cv2.dilate(binary_clean, kernel_v, iterations=1)
        
        kernel_c = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 1))
        binary_closed = cv2.morphologyEx(binary_dilated, cv2.MORPH_CLOSE, kernel_c)

        # Black text on White
        inverted = cv2.bitwise_not(binary_closed)

        # Crop to Content
        coords = np.where(inverted < 128)
        if len(coords[0]) > 0:
            padding = 6
            y_min, y_max = max(0, coords[0].min() - padding), min(h, coords[0].max() + padding + 1)
            x_min, x_max = max(0, coords[1].min() - padding), min(w, coords[1].max() + padding + 1)
            inverted = inverted[y_min:y_max, x_min:x_max]

        return inverted

    def solve(self, image_path):
        gray = self._load_image(image_path)
        processed_np = self._preprocess(gray)

        pil_img = Image.fromarray(processed_np)
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")

        result = self.ocr.classification(buf.getvalue())
        return result