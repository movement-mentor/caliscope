# %%

# NOTE: All measurements are now in millimeters (mm) as per standard metric conventions
# When the board is actually created in OpenCV, the board height is expressed
# in meters as a standard convention of science, and to improve
# readability of 3D positional output downstream

from collections import defaultdict
from itertools import combinations
import os

import cv2
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

import caliscope.logger

logger = caliscope.logger.get(__name__)

class Charuco:
    """
    create a charuco board that can be printed out and used for camera
    calibration, and used for drawing a grid during calibration
    """

    def __init__(
        self,
        columns,
        rows,
        square_marker_size_mm,
        dictionary="DICT_4X4_50",
        aruco_scale=0.75,
        inverted=False,
    ):
        """
        Create board based on shape and dimensions
        All measurements are in millimeters (mm)
        
        Parameters:        board_height_mm - height of the board in mm
        board_width_mm - width of the board in mm
        checker_width_mm - width of a checker square in mm (calculated from board dimensions if None)
        columns - number of columns in the board
        rows - number of rows in the board
        dictionary - ArUco dictionary to use
        aruco_scale - scale of ArUco markers relative to checker size
        inverted - whether to invert colors
        legacy_pattern - whether to use legacy pattern
        """
        self.columns = columns
        self.rows = rows
        self.square_marker_size_mm = square_marker_size_mm 
        self.dictionary = dictionary
        self.aruco_scale = aruco_scale
        self.inverted = inverted

    @property
    def dictionary_object(self):
        # grab the dictionary from the reference info at the foot of the module
        dictionary_integer = ARUCO_DICTIONARIES[self.dictionary]
        return cv2.aruco.getPredefinedDictionary(dictionary_integer)

    @property
    def board(self):
        marker_length = self.square_marker_size_mm * self.aruco_scale
        # create the board
        board = cv2.aruco.CharucoBoard(size=(self.columns, self.rows),
                                      squareLength=self.square_marker_size_mm,
                                      markerLength=marker_length,
                                      dictionary=self.dictionary_object,
        )

        return board

    def board_img(self, pixmap_scale=1000):
        """
        returns a cv2 image (numpy array) of the board
        smaller scale image by default for display to GUI
        provide larger pixmap_scale to get printer-ready image
        """

        ratio = self.columns / self.rows
        img = self.board.generateImage((pixmap_scale, int(pixmap_scale * ratio)))
        if self.inverted:
            img = ~img

        return img

    def board_pixmap(self, width, height):
        """
        Convert from an opencv image to QPixmap
        this can be used for creating thumbnail images
        """
        rgb_image = cv2.cvtColor(self.board_img(), cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        charuco_QImage = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        p = charuco_QImage.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        return QPixmap.fromImage(charuco_QImage)

    # def save_pdf(self, path):
    #     """
    #     Save the charuco board as a PDF file.
    #     The board is scaled to fit within the A4 page size while maintaining aspect ratio.
    #     """
    #     # If path doesn't end with .pdf, add it
    #     if not path.lower().endswith('.pdf'):
    #         path = path + '.pdf'
            
    #     # Generate high-resolution image
    #     img = self.board_img(pixmap_scale=10000)
    #     if self.inverted:
    #         img = ~img
            
    #     # Get image dimensions
    #     img_height, img_width = img.shape[:2]
        
    #     # Define page size in mm (A4)
    #     page_width, page_height = A4[0] / mm, A4[1] / mm
        
    #     # Calculate scaling to fit within the page with some margin
    #     margin = 10  # mm
    #     max_width = page_width - 2 * margin
    #     max_height = page_height - 2 * margin
        
    #     # Determine scaling factor to fit within page while maintaining aspect ratio
    #     scale = min(max_width / img_width, max_height / img_height)
        
    #     # Calculate final dimensions in mm
    #     final_width = img_width * scale
    #     final_height = img_height * scale
        
    #     # Calculate position to center on page
    #     x_offset = (page_width - final_width) / 2
    #     y_offset = (page_height - final_height) / 2
        
    #     # Create PDF
    #     c = canvas.Canvas(path, pagesize=A4)
        
    #     # Save temporary image file
    #     temp_img_path = os.path.splitext(path)[0] + "_temp.png"
    #     cv2.imwrite(temp_img_path, img)
        
    #     # Place image in PDF
    #     c.drawImage(temp_img_path, x_offset * mm, y_offset * mm, 
    #                width=final_width * mm, height=final_height * mm)
        
    #     # Add metadata
    #     c.setFont("Helvetica", 8)
    #     # Add actual dimensions text at bottom of page
    #     info_text = f"Board dimensions: {self.board_width_mm}mm x {self.board_height_mm}mm, "
    #     info_text += f"Checker width: {self.checker_width_mm or 'auto'}mm, "
    #     info_text += f"Grid: {self.rows}x{self.columns}"
        
    #     c.drawString(margin * mm, margin * mm / 2, info_text)
        
    #     # Save and close PDF
    #     c.save()
        
    #     # Remove temporary image file
    #     os.remove(temp_img_path)
        
    #     logger.info(f"Saved Charuco board as PDF to {path}")
        
    # def save_mirror_pdf(self, path):
    #     """
    #     Save a mirrored version of the charuco board as a PDF file.
    #     """
    #     # If path doesn't end with .pdf, add it
    #     if not path.lower().endswith('.pdf'):
    #         path = path + '.pdf'
            
    #     # Generate high-resolution image and mirror it
    #     img = self.board_img(pixmap_scale=10000)
    #     if self.inverted:
    #         img = ~img
    #     mirror = cv2.flip(img, 1)  # Flip horizontally
        
    #     # Get image dimensions
    #     img_height, img_width = mirror.shape[:2]
        
    #     # Define page size in mm (A4)
    #     page_width, page_height = A4[0] / mm, A4[1] / mm
        
    #     # Calculate scaling to fit within the page with some margin
    #     margin = 10  # mm
    #     max_width = page_width - 2 * margin
    #     max_height = page_height - 2 * margin
        
    #     # Determine scaling factor to fit within page while maintaining aspect ratio
    #     scale = min(max_width / img_width, max_height / img_height)
        
    #     # Calculate final dimensions in mm
    #     final_width = img_width * scale
    #     final_height = img_height * scale
        
    #     # Calculate position to center on page
    #     x_offset = (page_width - final_width) / 2
    #     y_offset = (page_height - final_height) / 2
        
    #     # Create PDF
    #     c = canvas.Canvas(path, pagesize=A4)
        
    #     # Save temporary image file
    #     temp_img_path = os.path.splitext(path)[0] + "_temp_mirror.png"
    #     cv2.imwrite(temp_img_path, mirror)
        
    #     # Place image in PDF
    #     c.drawImage(temp_img_path, x_offset * mm, y_offset * mm, 
    #                width=final_width * mm, height=final_height * mm)
        
    #     # Add metadata
    #     c.setFont("Helvetica", 8)
    #     # Add actual dimensions text at bottom of page
    #     info_text = f"Board dimensions: {self.board_width_mm}mm x {self.board_height_mm}mm, "
    #     info_text += f"Checker width: {self.checker_width_mm or 'auto'}mm, "
    #     info_text += f"Grid: {self.rows}x{self.columns} (MIRRORED)"
        
    #     c.drawString(margin * mm, margin * mm / 2, info_text)
        
    #     # Save and close PDF
    #     c.save()
        
    #     # Remove temporary image file
    #     os.remove(temp_img_path)
        
    #     logger.info(f"Saved mirrored Charuco board as PDF to {path}")

    def get_connected_points(self):
        """
        For a given board, returns a set of corner id pairs that will connect to form
        a grid pattern. This will provide the "object points" used by the calibration
        functions. It is the ground truth of how the points relate in the world.

        The return value is a *set* not a list
        """
        # create sets of the vertical and horizontal line positions
        corners = self.board.getChessboardCorners()
        corners_x = corners[:, 0]
        corners_y = corners[:, 1]
        x_set = set(corners_x)
        y_set = set(corners_y)

        lines = defaultdict(list)

        # put each point on the same vertical line in a list
        for x_line in x_set:
            for corner, x, y in zip(range(0, len(corners)), corners_x, corners_y):
                if x == x_line:
                    lines[f"x_{x_line}"].append(corner)

        # and the same for each point on the same horizontal line
        for y_line in y_set:
            for corner, x, y in zip(range(0, len(corners)), corners_x, corners_y):
                if y == y_line:
                    lines[f"y_{y_line}"].append(corner)

        # create a set of all sets of corner pairs that should be connected
        connected_corners = set()
        for lines, corner_ids in lines.items():
            for i in combinations(corner_ids, 2):
                connected_corners.add(i)

        return connected_corners

    def get_object_corners(self, corner_ids):
        """
        Given an array of corner IDs, provide an array of their relative
        position in a board frame of reference, originating from a corner position.
        """

        return self.board.chessboardCorners()[corner_ids, :]

    def summary(self):
        text = f"Columns: {self.columns}\n"
        text = text + f"Rows: {self.rows}\n"
        text = text + f"Square Size: {self.square_marker_size_mm} mm\n"
        text = text + f"Marker Size: {self.square_marker_size_mm * self.aruco_scale} mm\n"
        text = text + f"Inverted:  {self.inverted}\n"
        text = text + "\n"
        return text


################################## REFERENCE ###################################
ARUCO_DICTIONARIES = {
    "DICT_4X4_50": cv2.aruco.DICT_4X4_50,
    "DICT_4X4_100": cv2.aruco.DICT_4X4_100,
    "DICT_4X4_250": cv2.aruco.DICT_4X4_250,
    "DICT_4X4_1000": cv2.aruco.DICT_4X4_1000,
    "DICT_5X5_50": cv2.aruco.DICT_5X5_50,
    "DICT_5X5_100": cv2.aruco.DICT_5X5_100,
    "DICT_5X5_250": cv2.aruco.DICT_5X5_250,
    "DICT_5X5_1000": cv2.aruco.DICT_5X5_1000,
    "DICT_6X6_50": cv2.aruco.DICT_6X6_50,
    "DICT_6X6_100": cv2.aruco.DICT_6X6_100,
    "DICT_6X6_250": cv2.aruco.DICT_6X6_250,
    "DICT_6X6_1000": cv2.aruco.DICT_6X6_1000,
    "DICT_7X7_50": cv2.aruco.DICT_7X7_50,
    "DICT_7X7_100": cv2.aruco.DICT_7X7_100,
    "DICT_7X7_250": cv2.aruco.DICT_7X7_250,
    "DICT_7X7_1000": cv2.aruco.DICT_7X7_1000,
    "DICT_ARUCO_ORIGINAL": cv2.aruco.DICT_ARUCO_ORIGINAL,
    "DICT_APRILTAG_16h5": cv2.aruco.DICT_APRILTAG_16h5,
    "DICT_APRILTAG_25h9": cv2.aruco.DICT_APRILTAG_25h9,
    "DICT_APRILTAG_36h10": cv2.aruco.DICT_APRILTAG_36h10,
    "DICT_APRILTAG_36h11": cv2.aruco.DICT_APRILTAG_36h11,
}


if __name__ == "__main__":
    # Create a test board with all dimensions in mm
    charuco = Charuco(
        columns=4, 
        rows=5, 
        inverted=True
    )
    charuco.save_pdf("test_charuco.pdf")
    charuco.save_mirror_pdf("test_charuco_mirror.pdf")
    
    width, height = charuco.board_img().shape
    logger.info(f"Board width is {width}\nBoard height is {height}")

    corners = charuco.board.getChessboardCorners()
    logger.info(corners)

    logger.info(f"Charuco dictionary: {charuco.__dict__}")
    # while True:
    #     cv2.imshow("Charuco Board...'q' to quit", charuco.board_img)
    #     #
    #     key = cv2.waitKey(0)
    #     if key == ord("q"):
    #         cv2.destroyAllWindows()
    #         break

# %%
