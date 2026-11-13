#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DA-V Qt Compatibility Layer
Prioritizes PySide6 (LGPL v3 - Safe for Commercial & Closed-Source Distribution).
"""

import sys

try:
    from PySide6 import QtWidgets, QtCore, QtGui
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGridLayout, QTabWidget, QLabel, QPushButton, QLineEdit,
        QSpinBox, QComboBox, QCheckBox, QGroupBox, QTableWidget,
        QTableWidgetItem, QHeaderView, QTextEdit, QProgressBar,
        QSplitter, QFrame, QMessageBox, QFileDialog, QStackedWidget,
        QWizard, QWizardPage, QDialog, QScrollArea, QSizePolicy, QToolTip
    )
    from PySide6.QtCore import (
        Qt, QTimer, QThread, Signal, Slot, QSize, QPoint, QRect, QByteArray,
        QBuffer, QIODevice, QObject, QRectF, QPointF, QPropertyAnimation,
        QEasingCurve, Property
    )
    from PySide6.QtGui import (
        QIcon, QFont, QColor, QPalette, QPainter, QImage, QPixmap,
        QPen, QBrush, QLinearGradient, QShortcut, QKeySequence,
        QRadialGradient, QPainterPath, QCursor
    )
    QT_LIB = "PySide6"
except ImportError:
    try:
        from PyQt6 import QtWidgets, QtCore, QtGui
        from PyQt6.QtWidgets import (
            QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
            QGridLayout, QTabWidget, QLabel, QPushButton, QLineEdit,
            QSpinBox, QComboBox, QCheckBox, QGroupBox, QTableWidget,
            QTableWidgetItem, QHeaderView, QTextEdit, QProgressBar,
            QSplitter, QFrame, QMessageBox, QFileDialog, QStackedWidget,
            QWizard, QWizardPage, QDialog, QScrollArea, QSizePolicy, QToolTip
        )
        from PyQt6.QtCore import (
            Qt, QTimer, QThread, pyqtSignal as Signal, pyqtSlot as Slot,
            QSize, QPoint, QRect, QByteArray, QBuffer, QIODevice, QObject,
            QRectF, QPointF, QPropertyAnimation, QEasingCurve,
            pyqtProperty as Property
        )
        from PyQt6.QtGui import (
            QIcon, QFont, QColor, QPalette, QPainter, QImage, QPixmap,
            QPen, QBrush, QLinearGradient, QShortcut, QKeySequence,
            QRadialGradient, QPainterPath, QCursor
        )
        QT_LIB = "PyQt6"
    except ImportError as e:
        raise ImportError("Nenhuma biblioteca Qt encontrada. Instale PySide6 com 'pip install PySide6'.") from e
