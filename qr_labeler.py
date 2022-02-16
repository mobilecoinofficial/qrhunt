#! python3
import tempfile

from typing import Tuple, List, Optional, Any

import cv2
import numpy
import zbar
import zbar.misc

from PIL import Image

import imagehash


class QRLabeler:
    def __init__(self) -> None:
        self.qr_detector = cv2.QRCodeDetector()
        self.zbar_scanner = zbar.Scanner()

    def scan(self, image_path: str) -> Tuple[Optional[str], Optional[str]]:
        """ Scans an image using zbar """
        image_obj = Image.open(image_path)
        image = numpy.asarray(image_obj.convert("RGB"))
        phash = imagehash.phash(image_obj)
        ahash = imagehash.average_hash(image_obj)
        if len(image.shape) == 3:
            image = zbar.misc.rgb2gray(image)
        results = self.zbar_scanner.scan(image)
        for result in results:
            return ahash, phash, result.data.decode(), result.position
        return ahash, phash, None, None

    def process_file(self, input_file_name: str, output_queue: Any) -> List[Optional[str]]:
        """ Labels an image, scanning it with OpenCV and ZBAR, as well as looking for plausibly square QR code-ish things. """
        # reading image
        img = cv2.imread(input_file_name)
        ahash, phash, zbar_decoded, zbar_points = self.scan(input_file_name)
        # check image size
        #if sum(img.shape) < 1000:
        #    return [None]*4
        # converting image into grayscale image
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (9, 9), 0)

        decoded, points, box = self.qr_detector.detectAndDecode(gray)
        cv2.putText(
            img,
            f'ZBAR: {zbar_decoded or "ZBAR_ERROR"}',
            [40, 40],
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 0),
            2,
        )
        if zbar_decoded:
            zbar_points = zbar_points[:5]
            for (pt1, pt2) in zip(zbar_points, zbar_points[1::]):
                cv2.line(img, pt1, pt2, color=(255, 255, 0), thickness=3)


        if points is not None and decoded is not None:
            points = points[0]
            cv2.putText(
                img,
                f'OPENCV: {decoded or "ERROR"}',
                [80, 80],
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 0, 0),
                2,
            )
            for i in range(len(points)):
                pt1 = [int(val) for val in points[i]]
                pt2 = [int(val) for val in points[(i + 1) % 4]]
                cv2.line(img, pt1, pt2, color=(255, 0, 0), thickness=3)

        # setting threshold of gray image
        _, threshold = cv2.threshold(gray, 187, 255, cv2.THRESH_BINARY)

        # using a findContours() function
        contours, _ = cv2.findContours(
            threshold, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
        )

        i = 0
        has_square = None
        # list for storing names of shapes
        for countour_index, contour in enumerate(contours):
            # here we are ignoring first counter because
            # findcontour function detects whole image as shape
            if i == 0:
                i = 1
                continue

            # cv2.approxPloyDP() function to approximate the shape
            approx = cv2.approxPolyDP(
                contour, 0.01 * cv2.arcLength(contour, True), True
            )
            # using drawContours() function

            # finding center point of shape
            M = cv2.moments(contour)
            if M["m00"] != 0.0:
                x = int(M["m10"] / M["m00"])
                y = int(M["m01"] / M["m00"])

            # putting shape name at center of each shape
            c_area = cv2.contourArea(contour)
            if c_area > 400 and len(approx) == 4:
                has_square = "YES"
                cv2.drawContours(img, [contour], 0, (0, 0, 255), 5)
                cv2.putText(
                    img,
                    "CONTOUR",
                    (x, y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 0, 255),
                    2,
                )
                cv2.putText(
                    img,
                    "APPROX",
                    (approx[0][0][0] + 100, approx[0][0][1] + 100),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2,
                )
                for i in range(len(approx)):
                    pt1 = [int(val) for val in approx[i][0]]
                    pt2 = [int(val) for val in approx[(i + 1) % 4][0]]
                    cv2.line(img, pt1, pt2, color=(0, 255, 0), thickness=6)

        temp_file = tempfile.NamedTemporaryFile(
            prefix="rendered", suffix=".png", delete=False
        )

        cv2.imwrite(temp_file.name, img)
        results = [has_square, zbar_decoded, decoded, temp_file.name, str(phash), str(ahash)]
        if results and output_queue:
            output_queue.put(results)
        print(results)
        return results

if __name__ == "__main__":
    import sys
    labeler = QRLabeler()
    print(labeler.process_file(sys.argv[-1]))
