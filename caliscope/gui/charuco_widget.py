import sys
from pathlib import Path

import cv2

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import caliscope.logger
from caliscope.calibration.charuco import Charuco
from caliscope.controller import Controller
from caliscope.gui.utils.spinbox_utils import setup_spinbox_sizing

logger = caliscope.logger.get(__name__)


class CharucoWidget(QWidget):
    def __init__(self, controller: Controller):
        super().__init__()

        logger.info("Charuco Wizard initializing")
        self.controller = controller
        self.params = self.controller.get_charuco_params()

        # add group to do initial configuration of the charuco board
        self.charuco_config = CharucoConfigGroup(self.controller)
        self.charuco_config.row_spin.valueChanged.connect(self.build_charuco)
        self.charuco_config.column_spin.valueChanged.connect(self.build_charuco)
        self.charuco_config.square_marker_size_mm.valueChanged.connect(self.build_charuco)
        self.charuco_config.aruco_scale.valueChanged.connect(self.build_charuco)
        self.charuco_config.invert_checkbox.stateChanged.connect(self.build_charuco)

        # Build primary actions
        # self.build_save_png_group()

        # Build display of board
        self.charuco_added = False  # track to handle redrawing of board
        self.build_charuco()
        self.charuco_added = True
        # Create save button
        self.save_button = QPushButton("Save Charuco Board")
        self.save_button.clicked.connect(self.save_charuco_board)

        #################### ESTABLISH LARGELY VERTICAL LAYOUT ##############
        self.setLayout(QVBoxLayout())
        self.setWindowTitle("Charuco Board Builder")

        self.layout().addWidget(self.charuco_config)
        self.layout().setAlignment(self.charuco_config, Qt.AlignmentFlag.AlignHCenter)
        self.layout().addWidget(QLabel("<i>Top left corner is point (0,0,0) when setting capture volume origin</i>"))
        self.layout().addWidget(self.charuco_display, 2)
        self.layout().addSpacing(10)
        self.layout().addWidget(self.save_button)  # Add the save button to the layout
        
        # self.layout().addLayout(self.save_png_hbox)

        #################### ESTABLISH LARGELY VERTICAL LAYOUT ##############
        self.setLayout(QVBoxLayout())
        self.setWindowTitle("Charuco Board Builder")

        self.layout().addWidget(self.charuco_config)
        self.layout().setAlignment(self.charuco_config, Qt.AlignmentFlag.AlignHCenter)
        self.layout().addWidget(QLabel("<i>Top left corner is point (0,0,0) when setting capture volume origin</i>"))
        self.layout().addWidget(self.charuco_display, 2)
        self.layout().addWidget(self.save_button)  # Add the save button to the layout
        # self.layout().addSpacing(10)
        # self.layout().addLayout(self.save_png_hbox)

    def save_charuco_board(self):
        """Save the current Charuco board to the workspace directory"""
        try:
            # Get the workspace directory
            workspace_dir = self.controller.workspace
            
            if not workspace_dir:
                logger.error("No workspace directory configured")
                return
                
            # Create the path for saving
            save_path = Path(workspace_dir, "charuco") / "charuco_board.png"
            
            # Generate the board image at a higher resolution
            board_img = self.charuco.board_img()

            # Convert board image to RGB if it's grayscale
            if len(board_img.shape) == 2:
                board_img = cv2.cvtColor(board_img, cv2.COLOR_GRAY2BGR)
        
            # Save the image
            cv2.imwrite(save_path, board_img)
            
            logger.info(f"Charuco board saved to {save_path}")
        except Exception as e:
            logger.error(f"Failed to save Charuco board: {str(e)}")

    def build_charuco(self):
        columns = self.charuco_config.column_spin.value()
        rows = self.charuco_config.row_spin.value()
        aruco_scale = self.charuco_config.aruco_scale.value()
        inverted = self.charuco_config.invert_checkbox.isChecked()
        dictionary_str = self.params["dictionary"]
        square_marker_size_mm = self.charuco_config.square_marker_size_mm.value()
        #logger.info(f"Building charuco board with {columns} x {rows} squares, size {square_marker_size_mm} mm")
        self.charuco = Charuco(
            columns,
            rows,
            square_marker_size_mm,
            dictionary=dictionary_str,
            aruco_scale=aruco_scale,
            inverted=inverted,
        )

        if not self.charuco_added:
            self.charuco_display = QLabel()
            self.charuco_display.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # interesting problem comes up when scaling this... I want to switch between scaling the width and height
        # based on how these two things relate....

        logger.info("Building charuco thumbnail...")
        try:
            charuco_img = self.charuco.board_pixmap(columns*30, rows*30)
            self.charuco_display.setPixmap(charuco_img)
            # Clear any previous error message
            self.charuco_display.setStyleSheet("")
            self.charuco_display.setToolTip("")
            self.controller.update_charuco(self.charuco)
        except Exception as e:
            logger.error(f"Failed to create charuco board: {str(e)}")
            error_msg = """Unable to create board with current dimensions.\n
                        The default dictionary may by too small (can be configured in config.toml file).
                        Alternatively, the aspect ratio may be too extreme.
                        """
            self.charuco_display.setPixmap(QPixmap())  # Clear the pixmap
            self.charuco_display.setText(error_msg)
            # Optional: Add some styling to make the error message stand out
            self.charuco_display.setStyleSheet("QLabel { color: red; }")
            self.charuco_display.setToolTip("Try adjusting the width and height to have a less extreme ratio")



class CharucoConfigGroup(QWidget):
    def __init__(self, controller: Controller):
        super().__init__()
        self.controller = controller
        self.params = self.controller.config.dict["charuco"]

        self.column_spin = QSpinBox()
        setup_spinbox_sizing(self.column_spin, min_value=3, max_value=999, padding=10)
        self.column_spin.setValue(self.params["columns"])
        self.column_spin.setSingleStep(1)

        self.row_spin = QSpinBox()
        self.row_spin.setValue(self.params["rows"])
        setup_spinbox_sizing(self.row_spin, min_value=4, max_value=999, padding=10)
        self.row_spin.setSingleStep(1)

        self.square_marker_size_mm = QDoubleSpinBox()
        self.square_marker_size_mm.setValue(self.params["square_marker_size_mm"])
        setup_spinbox_sizing(self.square_marker_size_mm, min_value=1, max_value=9999, padding=10)
        self.square_marker_size_mm.setSingleStep(1)

        self.aruco_scale = QDoubleSpinBox()
        self.aruco_scale.setValue(self.params["aruco_scale"])
        setup_spinbox_sizing(self.aruco_scale, min_value=0, max_value=9999, padding=10)
        self.aruco_scale.setSingleStep(0.01)

        self.invert_checkbox = QCheckBox("&Invert")
        self.invert_checkbox.setChecked(self.params["inverted"])
        
        #####################  HORIZONTAL CONFIG BOX  ########################
        self.config_options = QHBoxLayout()
        self.config_options.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.charuco_config = QGroupBox("&Configure Charuco Board")

        self.setLayout(self.config_options)

        ########################## SQUARE SIZE ################################
        size_grp = QGroupBox("Square Size (mm)")
        size_grp.setLayout(QHBoxLayout())
        size_grp.layout().setAlignment(Qt.AlignmentFlag.AlignHCenter)

        size_grp.layout().addWidget(self.square_marker_size_mm)
        size_grp.layout().addWidget(QLabel("mm"))


        self.config_options.addWidget(size_grp)
        
        ########################## ARUCO SCALE ################################
        aruco_grp = QGroupBox("Aruco Scale")
        aruco_grp.setLayout(QHBoxLayout())
        aruco_grp.layout().setAlignment(Qt.AlignmentFlag.AlignHCenter)
        aruco_grp.layout().addWidget(self.aruco_scale)
        self.config_options.addWidget(aruco_grp)
        
        ### SHAPE GROUP    ################################################
        shape_grp = QGroupBox("row x col")
        shape_grp.setLayout(QHBoxLayout())
        shape_grp.layout().setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # These are reversed from 'row x col', but this is how it works out
        shape_grp.layout().addWidget(self.row_spin)
        shape_grp.layout().addWidget(self.column_spin)

        self.config_options.addWidget(shape_grp)

        ############################# INVERT ####################################
        self.config_options.addWidget(self.invert_checkbox)

