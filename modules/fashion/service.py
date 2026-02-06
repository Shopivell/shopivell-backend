"""
Body Measurement Service

Extracts human body measurements from front and side pose images using
computer vision (MediaPipe + MiDaS depth estimation + OpenCV contour detection).

Based on: https://github.com/JavTahir/Live-Measurements-Api
"""

import cv2
import numpy as np
import mediapipe as mp
import torch
import torch.nn.functional as F
from typing import Dict, Optional, Tuple, Any

mp_pose = mp.solutions.pose
mp_holistic = mp.solutions.holistic

KNOWN_OBJECT_WIDTH_CM = 21.0  # A4 paper width
FOCAL_LENGTH = 600
DEFAULT_HEIGHT_CM = 152.0

# Lazy-loaded globals
_depth_model = None
_holistic = None


def _get_depth_model():
    global _depth_model
    if _depth_model is None:
        _depth_model = torch.hub.load("intel-isl/MiDaS", "MiDaS_small")
        _depth_model.eval()
    return _depth_model


def _get_holistic():
    global _holistic
    if _holistic is None:
        _holistic = mp_holistic.Holistic()
    return _holistic


def calibrate_focal_length(real_width_cm: float, detected_width_px: float) -> float:
    return (detected_width_px * FOCAL_LENGTH) / real_width_cm if detected_width_px else FOCAL_LENGTH


def detect_reference_object(image: np.ndarray) -> Tuple[float, float]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        largest_contour = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(largest_contour)
        focal_length = calibrate_focal_length(KNOWN_OBJECT_WIDTH_CM, w)
        scale_factor = KNOWN_OBJECT_WIDTH_CM / w
        return scale_factor, focal_length
    return 0.05, FOCAL_LENGTH


def estimate_depth(image: np.ndarray) -> np.ndarray:
    model = _get_depth_model()
    input_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB) / 255.0
    input_tensor = torch.tensor(input_image, dtype=torch.float32).permute(2, 0, 1).unsqueeze(0)
    input_tensor = F.interpolate(input_tensor, size=(384, 384), mode="bilinear", align_corners=False)
    with torch.no_grad():
        depth_map = model(input_tensor)
    return depth_map.squeeze().numpy()


def calculate_distance_using_height(landmarks, image_height: int, user_height_cm: float) -> Tuple[float, float]:
    top_head = landmarks[mp_pose.PoseLandmark.NOSE.value].y * image_height
    bottom_foot = max(
        landmarks[mp_pose.PoseLandmark.LEFT_ANKLE.value].y,
        landmarks[mp_pose.PoseLandmark.RIGHT_ANKLE.value].y,
    ) * image_height
    person_height_px = abs(bottom_foot - top_head)
    distance = (user_height_cm * FOCAL_LENGTH) / person_height_px
    scale_factor = user_height_cm / person_height_px
    return distance, scale_factor


def get_body_width_at_height(frame: np.ndarray, height_px: int, center_x: float) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blur, 50, 255, cv2.THRESH_BINARY)

    if height_px >= frame.shape[0]:
        height_px = frame.shape[0] - 1

    horizontal_line = thresh[height_px, :]
    center_x = int(center_x * frame.shape[1])
    left_edge, right_edge = center_x, center_x

    for i in range(center_x, 0, -1):
        if horizontal_line[i] == 0:
            left_edge = i
            break

    for i in range(center_x, len(horizontal_line)):
        if horizontal_line[i] == 0:
            right_edge = i
            break

    width_px = right_edge - left_edge
    min_width = 0.1 * frame.shape[1]
    if width_px < min_width:
        width_px = min_width
    return width_px


def calculate_measurements(
    results, scale_factor: float, image_width: int, image_height: int,
    depth_map: Optional[np.ndarray], frame: Optional[np.ndarray] = None,
    user_height_cm: Optional[float] = None,
) -> Dict[str, float]:
    landmarks = results.pose_landmarks.landmark

    if user_height_cm:
        _, scale_factor = calculate_distance_using_height(landmarks, image_height, user_height_cm)

    def pixel_to_cm(value):
        return round(value * scale_factor, 2)

    def calculate_circumference(width_px, depth_ratio=1.0):
        width_cm = width_px * scale_factor
        estimated_depth_cm = width_cm * depth_ratio * 0.7
        half_width = width_cm / 2
        half_depth = estimated_depth_cm / 2
        return round(2 * np.pi * np.sqrt((half_width**2 + half_depth**2) / 2), 2)

    measurements: Dict[str, float] = {}

    # --- Shoulder ---
    left_shoulder = landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER.value]
    right_shoulder = landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER.value]
    shoulder_width_px = abs(left_shoulder.x * image_width - right_shoulder.x * image_width) * 1.1
    measurements["shoulder_width"] = pixel_to_cm(shoulder_width_px)

    # --- Chest ---
    chest_y_ratio = 0.15
    chest_y = left_shoulder.y + (landmarks[mp_pose.PoseLandmark.LEFT_HIP.value].y - left_shoulder.y) * chest_y_ratio
    chest_width_px = abs((right_shoulder.x - left_shoulder.x) * image_width) * 1.15

    if frame is not None:
        chest_y_px = int(chest_y * image_height)
        center_x = (left_shoulder.x + right_shoulder.x) / 2
        detected_width = get_body_width_at_height(frame, chest_y_px, center_x)
        if detected_width > 0:
            chest_width_px = max(chest_width_px, detected_width)

    chest_depth_ratio = 1.0
    if depth_map is not None:
        chest_x = int(((left_shoulder.x + right_shoulder.x) / 2) * image_width)
        chest_y_px = int(chest_y * image_height)
        scale_y = 384 / image_height
        scale_x = 384 / image_width
        cy = int(chest_y_px * scale_y)
        cx = int(chest_x * scale_x)
        if 0 <= cy < 384 and 0 <= cx < 384:
            chest_depth = depth_map[cy, cx]
            max_depth = np.max(depth_map)
            chest_depth_ratio = 1.0 + 0.5 * (1.0 - chest_depth / max_depth)

    measurements["chest_width"] = pixel_to_cm(chest_width_px)
    measurements["chest_circumference"] = calculate_circumference(chest_width_px, chest_depth_ratio)

    # --- Waist ---
    left_hip = landmarks[mp_pose.PoseLandmark.LEFT_HIP.value]
    right_hip = landmarks[mp_pose.PoseLandmark.RIGHT_HIP.value]
    waist_y_ratio = 0.35
    waist_y = left_shoulder.y + (left_hip.y - left_shoulder.y) * waist_y_ratio

    if frame is not None:
        waist_y_px = int(waist_y * image_height)
        center_x = (left_hip.x + right_hip.x) / 2
        detected_width = get_body_width_at_height(frame, waist_y_px, center_x)
        waist_width_px = detected_width if detected_width > 0 else abs(right_hip.x - left_hip.x) * image_width * 0.9
    else:
        waist_width_px = abs(right_hip.x - left_hip.x) * image_width * 0.9

    waist_width_px *= 1.16

    waist_depth_ratio = 1.0
    if depth_map is not None:
        waist_x = int(((left_hip.x + right_hip.x) / 2) * image_width)
        waist_y_px = int(waist_y * image_height)
        scale_y = 384 / image_height
        scale_x = 384 / image_width
        wy = int(waist_y_px * scale_y)
        wx = int(waist_x * scale_x)
        if 0 <= wy < 384 and 0 <= wx < 384:
            waist_depth = depth_map[wy, wx]
            max_depth = np.max(depth_map)
            waist_depth_ratio = 1.0 + 0.5 * (1.0 - waist_depth / max_depth)

    measurements["waist_width"] = pixel_to_cm(waist_width_px)
    measurements["waist"] = calculate_circumference(waist_width_px, waist_depth_ratio)

    # --- Hip ---
    hip_width_px = abs(left_hip.x * image_width - right_hip.x * image_width) * 1.35

    if frame is not None:
        hip_y_offset = 0.1
        hip_y = left_hip.y + (landmarks[mp_pose.PoseLandmark.LEFT_KNEE.value].y - left_hip.y) * hip_y_offset
        hip_y_px = int(hip_y * image_height)
        center_x = (left_hip.x + right_hip.x) / 2
        detected_width = get_body_width_at_height(frame, hip_y_px, center_x)
        if detected_width > 0:
            hip_width_px = max(hip_width_px, detected_width)

    hip_depth_ratio = 1.0
    if depth_map is not None:
        hip_x = int(((left_hip.x + right_hip.x) / 2) * image_width)
        hip_y_px = int(left_hip.y * image_height)
        scale_y = 384 / image_height
        scale_x = 384 / image_width
        hy = int(hip_y_px * scale_y)
        hx = int(hip_x * scale_x)
        if 0 <= hy < 384 and 0 <= hx < 384:
            hip_depth = depth_map[hy, hx]
            max_depth = np.max(depth_map)
            hip_depth_ratio = 1.0 + 0.5 * (1.0 - hip_depth / max_depth)

    measurements["hip_width"] = pixel_to_cm(hip_width_px)
    measurements["hip"] = calculate_circumference(hip_width_px, hip_depth_ratio)

    # --- Neck ---
    neck = landmarks[mp_pose.PoseLandmark.NOSE.value]
    left_ear = landmarks[mp_pose.PoseLandmark.LEFT_EAR.value]
    neck_width_px = abs(neck.x * image_width - left_ear.x * image_width) * 2.0
    measurements["neck"] = calculate_circumference(neck_width_px, 1.0)
    measurements["neck_width"] = pixel_to_cm(neck_width_px)

    # --- Arm length ---
    left_wrist = landmarks[mp_pose.PoseLandmark.LEFT_WRIST.value]
    sleeve_length_px = abs(left_shoulder.y * image_height - left_wrist.y * image_height)
    measurements["arm_length"] = pixel_to_cm(sleeve_length_px)

    # --- Shirt length ---
    shirt_length_px = abs(left_shoulder.y * image_height - left_hip.y * image_height) * 1.2
    measurements["shirt_length"] = pixel_to_cm(shirt_length_px)

    # --- Thigh ---
    left_knee = landmarks[mp_pose.PoseLandmark.LEFT_KNEE.value]
    thigh_y_ratio = 0.2
    thigh_y = left_hip.y + (left_knee.y - left_hip.y) * thigh_y_ratio
    thigh_width_px = hip_width_px * 0.5 * 1.2

    if frame is not None:
        thigh_y_px = int(thigh_y * image_height)
        thigh_x = left_hip.x * 0.9
        detected_width = get_body_width_at_height(frame, thigh_y_px, thigh_x)
        if 0 < detected_width < hip_width_px:
            thigh_width_px = detected_width

    thigh_depth_ratio = 1.0
    if depth_map is not None:
        thigh_x_val = int(left_hip.x * image_width)
        thigh_y_px = int(thigh_y * image_height)
        scale_y = 384 / image_height
        scale_x = 384 / image_width
        ty = int(thigh_y_px * scale_y)
        tx = int(thigh_x_val * scale_x)
        if 0 <= ty < 384 and 0 <= tx < 384:
            thigh_depth = depth_map[ty, tx]
            max_depth = np.max(depth_map)
            thigh_depth_ratio = 1.0 + 0.5 * (1.0 - thigh_depth / max_depth)

    measurements["thigh"] = pixel_to_cm(thigh_width_px)
    measurements["thigh_circumference"] = calculate_circumference(thigh_width_px, thigh_depth_ratio)

    # --- Trouser length ---
    left_ankle = landmarks[mp_pose.PoseLandmark.LEFT_ANKLE.value]
    trouser_length_px = abs(left_hip.y * image_height - left_ankle.y * image_height)
    measurements["trouser_length"] = pixel_to_cm(trouser_length_px)

    return measurements


def validate_front_image(image_np: np.ndarray) -> Tuple[bool, str]:
    """Validate that a full body is visible in the front image."""
    try:
        rgb_frame = cv2.cvtColor(image_np, cv2.COLOR_BGR2RGB)
        image_height, image_width = image_np.shape[:2]

        with mp_holistic.Holistic(
            static_image_mode=True,
            model_complexity=1,
            enable_segmentation=False,
            refine_face_landmarks=False,
        ) as holistic:
            results = holistic.process(rgb_frame)

        if not hasattr(results, "pose_landmarks") or not results.pose_landmarks:
            return False, "No person detected. Please make sure you're clearly visible in the frame."

        MINIMUM_LANDMARKS = [
            mp_holistic.PoseLandmark.NOSE,
            mp_holistic.PoseLandmark.LEFT_SHOULDER,
            mp_holistic.PoseLandmark.RIGHT_SHOULDER,
            mp_holistic.PoseLandmark.LEFT_ELBOW,
            mp_holistic.PoseLandmark.RIGHT_ELBOW,
            mp_holistic.PoseLandmark.RIGHT_KNEE,
            mp_holistic.PoseLandmark.LEFT_KNEE,
        ]

        missing = []
        for landmark in MINIMUM_LANDMARKS:
            ld = results.pose_landmarks.landmark[landmark]
            if ld.visibility < 0.5 or ld.x < 0 or ld.x > 1 or ld.y < 0 or ld.y > 1:
                missing.append(landmark.name.replace("_", " "))

        if missing:
            return False, "Couldn't detect full body. Please make sure your full body is visible."

        nose = results.pose_landmarks.landmark[mp_holistic.PoseLandmark.NOSE]
        left_shoulder = results.pose_landmarks.landmark[mp_holistic.PoseLandmark.LEFT_SHOULDER]
        right_shoulder = results.pose_landmarks.landmark[mp_holistic.PoseLandmark.RIGHT_SHOULDER]
        shoulder_width = abs(left_shoulder.x - right_shoulder.x) * image_width
        head_to_shoulder = abs(left_shoulder.y - nose.y) * image_height
        if shoulder_width < head_to_shoulder * 1.2:
            return False, "Please step back to show more of your upper body, not just your face."

        return True, "Validation passed"
    except Exception as e:
        return False, f"Image validation error: {str(e)}"


def process_images(
    front_image_bytes: bytes,
    side_image_bytes: Optional[bytes] = None,
    user_height_cm: float = DEFAULT_HEIGHT_CM,
) -> Dict[str, Any]:
    """
    Process front (and optional side) images and return body measurements.

    Args:
        front_image_bytes: Raw bytes of front-facing full-body photo
        side_image_bytes: Optional raw bytes of side-view photo
        user_height_cm: User's real height in cm for calibration (default 152)

    Returns:
        Dict with "measurements" and "debug_info" keys

    Raises:
        ValueError: If image is invalid or body can't be detected
    """
    # Decode front image
    front_np = np.frombuffer(front_image_bytes, np.uint8)
    front_frame = cv2.imdecode(front_np, cv2.IMREAD_COLOR)
    if front_frame is None:
        raise ValueError("Could not decode front image. Please upload a valid JPEG/PNG.")

    # Validate front image
    is_valid, error_msg = validate_front_image(front_frame)
    if not is_valid:
        raise ValueError(error_msg)

    holistic = _get_holistic()
    measurements: Dict[str, float] = {}
    scale_factor = None
    focal_length = FOCAL_LENGTH
    frames = {"front": front_frame}
    results = {}

    # Process front image
    rgb_front = cv2.cvtColor(front_frame, cv2.COLOR_BGR2RGB)
    results["front"] = holistic.process(rgb_front)
    image_height, image_width, _ = front_frame.shape

    if results["front"].pose_landmarks:
        _, scale_factor = calculate_distance_using_height(
            results["front"].pose_landmarks.landmark, image_height, user_height_cm
        )
    else:
        scale_factor, focal_length = detect_reference_object(front_frame)

    depth_map = estimate_depth(front_frame)

    if results["front"].pose_landmarks:
        measurements.update(
            calculate_measurements(
                results["front"], scale_factor, image_width, image_height,
                depth_map, front_frame, user_height_cm,
            )
        )

    # Process side image if provided
    if side_image_bytes:
        side_np = np.frombuffer(side_image_bytes, np.uint8)
        side_frame = cv2.imdecode(side_np, cv2.IMREAD_COLOR)
        if side_frame is not None:
            rgb_side = cv2.cvtColor(side_frame, cv2.COLOR_BGR2RGB)
            results["left_side"] = holistic.process(rgb_side)
            # Side image used for improved depth/circumference in future

    debug_info = {
        "scale_factor": float(scale_factor) if scale_factor else None,
        "focal_length": float(focal_length),
        "user_height_cm": float(user_height_cm),
    }

    return {"measurements": measurements, "debug_info": debug_info}
