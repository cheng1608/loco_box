"""屏幕区域截图。"""

import cv2
import mss
import numpy as np

Region = dict


def grab_region(region: Region) -> np.ndarray:
    """使用 mss 截取指定区域，返回 BGR numpy 数组。"""
    with mss.mss() as sct:
        shot = sct.grab(region)
        img = np.array(shot)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
