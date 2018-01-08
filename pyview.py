#! /usr/bin/env python3

# Simple Photo Collage application
#
# Author: Oxben <oxben@free.fr>
#
# -*- coding: utf-8 -*-

import getopt
import json
import logging
import math
import os
import sys
from urllib.parse import *

from PyQt5.QtWidgets import QApplication, QWidget, QHBoxLayout
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QGraphicsView, QGraphicsScene
from PyQt5.QtWidgets import QFileDialog, QOpenGLWidget

from PyQt5.QtGui import QPainter, QPen, QBrush, QPixmap, QImage, QIcon, QDrag, QColor

from PyQt5.QtCore import QRect, QRectF, QPoint, QPointF, QSize, Qt, QMimeData, QUrl


RotOffset   = 5.0
ScaleOffset = 0.05
SmallScaleOffset = 0.01
MaxZoom     = 2.0
FrameRadius = 15.0
FrameWidth  = 10.0
CollageAspectRatio = (2.0 / 3.0)
CollageSize = QRectF(0, 0, 1024, 1024 * CollageAspectRatio)
LimitDrag   = True
OutFileName = "out.png"
FrameBgColor = QColor(232, 232, 232)

OpenGLRender = False

filenames = []
app = None

HelpCommands = [
    ('Left Button',   'Drag image'),
    ('Right Button',  'Drag to swap two images'),
    ('Wheel',         'Zoom image'),
    ('Shift + Wheel', 'Rotate image'),
    ('Double Click',  'Load new image'),
    ('+/-',           'Increase/Decrease photo frame'),
    ('Shift + S',     'Save as collage'),
    ('S',             'Save collage'),
    ('Numpad /',      'Reset photo position, scale and rotation'),
]

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


#-------------------------------------------------------------------------------
class PhotoFrameItem(QGraphicsItem):
    '''The frame around a photo'''
    def __init__(self, rect, parent = None):
        super(PhotoFrameItem, self).__init__(parent)
        self.rect = rect
        self.photo = None
        # Set flags
        self.setFlags(self.flags() |
                      QGraphicsItem.ItemClipsChildrenToShape |
                      QGraphicsItem.ItemIsFocusable)
        self.setAcceptDrops(True)
        self.setAcceptHoverEvents(True)

    def setPhoto(self, photo, reset=True):
        '''Set PhotoItem associated to this frame'''
        self.photo = photo
        self.photo.setParentItem(self)
        if reset:
            self.photo.reset()
            self.fitPhoto()
        self.update()

    def fitPhoto(self):
        '''Fit photo to frame'''
        photoWidth = self.photo.pixmap().width()
        height = self.photo.pixmap().height()
        frameWidth = self.rect.width()
        if photoWidth > frameWidth:
            self.photo.setScale(self.photo.scale() * (frameWidth / photoWidth))

    def boundingRect(self):
        return QRectF(self.rect)

    def paint(self, painter, option, widget = None):
        pen = painter.pen()
        pen.setColor(Qt.white)
        #pen.setWidth(FrameWidth)
        pen.setWidth(FrameRadius)
        painter.setPen(pen)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawRoundedRect(self.rect.left(), self.rect.top(),
                                self.rect.width(), self.rect.height(),
                                FrameRadius, FrameRadius)

    def hoverEnterEvent(self, event):
        # Request keyboard events
        self.setFocus()

    def hoverLeaveEvent(self, event):
        self.clearFocus()

    def keyReleaseEvent(self, event):
        logger.debug(str(event.key()))
        if event.key() == Qt.Key_Slash:
            # Reset photo pos, scale and rotation
            self.photo.reset()

    def mouseDoubleClickEvent(self, event):
        filename, filetype = QFileDialog.getOpenFileName(None, 'Open File', os.getcwd(), \
            "Images (*.png *.gif *.jpg);;All Files (*)")
        logger.info('Open image file: %s' % filename)
        self.photo.setPhoto(filename)

    def dragEnterEvent(self, event):
        logger.debug('dragEnterEvent')
        mimeData = event.mimeData()
        if (mimeData.hasUrls() and len(mimeData.urls()) == 1) or mimeData.hasText():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        mimeData = event.mimeData()
        logger.debug('dropEvent: mimeData=%s' % str(mimeData.urls()))
        logger.debug('dropEvent: dict=%s pos=%s' % (dir(event), str(event.scenePos())))
        if event.proposedAction() == Qt.CopyAction and mimeData.hasUrls():
            # New photo
            filePath = mimeData.urls()[0].toLocalFile()
            logger.debug("File dragged'n'dropped: %s" % filePath)
            self.photo.setPhoto(filePath)
        elif event.proposedAction() == Qt.MoveAction and mimeData.hasText():
            # Swap photos
            # Get source PhotoFrameItem and swap its photo
            logger.debug('mimeData.text=%s' % mimeData.text())
            try:
                sourcePos = json.loads(mimeData.text())
                items = self.scene().items(QPointF(sourcePos['pos']['x'], sourcePos['pos']['y']))
                if items:
                    for srcItem in items:
                        if isinstance(srcItem, PhotoFrameItem):
                            photoItem = srcItem.photo
                            srcItem.setPhoto(self.photo, reset=False)
                            self.setPhoto(photoItem, reset=False)
            except Exception:
                logger.debug('dropEvent: not a "photo swap" event: %s' % mimeData.text())


#-------------------------------------------------------------------------------
class PhotoItem(QGraphicsPixmapItem):
    '''A photo item'''
    def __init__(self, filename):
        self.filename = filename
        super(PhotoItem, self).__init__(QPixmap(self.filename), parent=None)
        self.dragStartPosition = None
        self.reset()
        # Use bilinear filtering
        self.setTransformationMode(Qt.SmoothTransformation)
        # Set flags
        self.setFlags(self.flags() |
                      QGraphicsItem.ItemIsMovable |
                      QGraphicsItem.ItemStacksBehindParent)

    def setPhoto(self, filename):
        pixmap = QPixmap(filename)
        if pixmap.width() > 0:
            logger.debug('SetPhoto(): %d %d' % (pixmap.width(), pixmap.height()))
            self.filename = filename
            super(PhotoItem, self).setPixmap(pixmap)
            self.reset()

    def setPixmap(self, pixmap):
        super(PhotoItem, self).setPixmap(pixmap)
        self.reset()

    def reset(self):
        # Center photo in frame
        if self.parentItem() != None:
            frameRect = self.parentItem().boundingRect()
            self.setPos((frameRect.width() / 2) - (self.pixmap().width() / 2),
                        (frameRect.height() / 2) - (self.pixmap().height() / 2))
        # Set transform origin to center of pixmap
        origx = self.pixmap().width() / 2
        origy = self.pixmap().height() / 2
        self.setTransformOriginPoint(origx, origy)
        # Reset transformation
        self.setScale(1.0)
        self.setRotation(0.0)

    def mouseDoubleClickEvent(self, event):
        if self.parentItem():
            # Forward event to parent frame
            self.parentItem().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        scale = self.scale()
        rot   = self.rotation()
        if event.delta() > 0:
            logger.debug('Zoom')
            rot += RotOffset
            if scale < MaxZoom:
                if round(scale, 2) < round(ScaleOffset * 2, 2):
                    scale += SmallScaleOffset
                else:
                    scale += ScaleOffset
        else:
            logger.debug('Unzoom')
            rot -= RotOffset
            if scale >= ScaleOffset * 2:
                scale -= ScaleOffset
            elif scale >= SmallScaleOffset * 2:
                scale -= SmallScaleOffset
        # Transform based on mouse position
        # XXX: doesn't work well
        #self.setTransformOriginPoint(event.pos())
        modifiers = event.modifiers()
        if modifiers == Qt.NoModifier:
            self.setScale(scale)
            logger.debug('scale=%f' % (scale))
        elif modifiers == Qt.ShiftModifier:
            self.setRotation(rot)
            logger.debug('rotation=%f' % (rot))
        elif modifiers == (Qt.ShiftModifier|Qt.ControlModifier):
            self.setScale(scale)
            self.setRotation(rot)
            logger.debug('scale=%f rotation=%f' % (scale, rot))

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.dragStartPosition = event.pos()
        else:
            super(PhotoItem, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.RightButton:
            if (event.pos() - self.dragStartPosition).manhattanLength() < QApplication.startDragDistance():
                return;
            else:
                # Initiate "swap photos" action
                # Pass source PhotoFrameItem coordinates in json format
                drag = QDrag(event.widget())
                mimeData = QMimeData()
                mimeData.setText('{ "pos": { "x" : %f, "y" : %f }}' % (event.scenePos().x(), event.scenePos().y()))
                drag.setMimeData(mimeData)
                dropAction = drag.exec_(Qt.MoveAction)
                logger.debug('dropAction=%s' % str(dropAction))
        else:
            super(PhotoItem, self).mouseMoveEvent(event)


#-------------------------------------------------------------------------------
class ImageView(QGraphicsView):
    '''GraphicsView containing the scene'''
    def __init__(self, parent=None):
        super(ImageView, self).__init__(parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        # Hide scrollbars
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.helpItem = None

    def keyReleaseEvent(self, event):
        global FrameRadius
        global OutFileName
        logger.debug('Key event: %d' % event.key())
        modifiers = event.modifiers()
        key = event.key()
        if key == Qt.Key_Plus:
            # Increase frame width
            FrameRadius += 1.0
            self.viewport().update()

        elif key == Qt.Key_Minus:
            # Decrease frame width
            FrameRadius = max(0, FrameRadius - 1.0)
            self.viewport().update()

        elif key == Qt.Key_H:
            # Show help
            if self.helpItem:
                self.helpItem.setVisible(not self.helpItem.isVisible())
            else:
                self.helpItem = HelpItem(QRect(50, 50, 700, 500))
                self.scene().addItem(self.helpItem)

        elif key == Qt.Key_S:
            # Save collage to output file
            if (modifiers == Qt.NoModifier and not OutFileName) or \
               modifiers == Qt.ShiftModifier:
                OutFileName, filetype = QFileDialog.getSaveFileName(None, 'Save Collage', os.getcwd(), \
                    "Images (*.png *.gif *.jpg);;All Files (*)")
            elif modifiers == Qt.ControlModifier:
                return
            logger.info("Collage saved to file: %s" % OutFileName)

            self.scene().clearSelection()
            image = QImage(CollageSize.width(), CollageSize.height(), QImage.Format_RGB32)
            image.fill(Qt.black)
            painter = QPainter(image)
            painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
            self.render(painter)
            image.save(OutFileName)
            # Explicitely delete painter to avoid the following error:
            # "QPaintDevice: Cannot destroy paint device that is being painted" + SIGSEV
            del painter

        else:
            # Pass event to default handler
            super(ImageView, self).keyReleaseEvent(event)

    def heightForWidth(self, w):
        logger.debug('heightForWidth(%d)' % w)
        return w

    def resizeEvent(self, event):
        self.fitInView(CollageSize, Qt.KeepAspectRatio)

    def wheelEvent(self, event):
        # Filter wheel events
        items = self.items(event.pos())
        logger.debug('Wheel event: %s' % str(items))
        if items:
            for item in items:
                if isinstance(item, PhotoItem):
                    super(ImageView, self).wheelEvent(event)

#-------------------------------------------------------------------------------
class HelpItem(QGraphicsItem):
    '''Online help'''
    def __init__(self, rect, parent = None):
        super(HelpItem, self).__init__(parent)
        self.rect = rect

    def boundingRect(self):
        return QRectF(self.rect)

    def paint(self, painter, option, widget = None):
        painter.setRenderHint(QPainter.Antialiasing)

        pen = painter.pen()
        pen.setColor(QColor(128, 128, 128, 200))
        pen.setWidth(3)
        painter.setPen(pen)
        brush = painter.brush()
        brush.setColor(QColor(0, 0, 0, 200))
        brush.setStyle(Qt.SolidPattern)
        painter.setBrush(brush)

        painter.drawRoundedRect(self.rect.left(), self.rect.top(),
                                self.rect.width(), self.rect.height(),
                                15, 15)

        font = painter.font()
        font.setPixelSize(32)
        painter.setFont(font)
        pen = painter.pen()
        pen.setColor(QColor(255, 255, 255, 232))
        painter.setPen(pen)
        point = self.rect.topLeft() + QPoint(20, 40)
        painter.drawText(point, 'Help')

        font.setPixelSize(24)
        painter.setFont(font)
        point += QPoint(0, 16)
        for cmd, desc in HelpCommands:
            point += QPoint(0, 32)
            painter.drawText(point, cmd)
            painter.drawText(point + QPoint(200, 0), desc)


#-------------------------------------------------------------------------------
class CollageScene(QGraphicsScene):
    '''Scene containing the frames and the photos'''
    def __init__(self):
        super(CollageScene, self).__init__()
        # Add rect to provide background for PhotoFrameItem
        pen = QPen(FrameBgColor)
        brush = QBrush(FrameBgColor)
        self.addRect(QRectF(1 , 1, CollageSize.width() - 2, CollageSize.height() - 2), pen, brush)

    def addPhoto(self, rect, filepath):
        logger.info('Add image: %s' % filepath)
        frame = PhotoFrameItem(QRect(0, 0, rect.width(), rect.height()))
        frame.setPos(rect.x(), rect.y())
        photo = PhotoItem(filepath)
        frame.setPhoto(photo)
        # Add frame to scene
        fr = self.addItem(frame)


#-------------------------------------------------------------------------------
class LoopIter:
    '''Infinite iterator: loop on list elements, wrapping to first element when last element is reached'''
    def __init__(self, l):
        self.i = 0
        self.l = l

    def __iter__(self):
        return self

    def next(self):
        item = self.l[self.i]
        self.i = (self.i + 1)  % len(self.l)
        return item

def create_3_2B_3_collage(scene):
    f = LoopIter(filenames)
    # First column
    x = 0
    photoWidth  = CollageSize.width() / 4
    photoHeight =  CollageSize.height() / 3
    for y in range(0, 3):
        scene.addPhoto(QRect(x, y * photoHeight, photoWidth, photoHeight), f.next())
    # Second column
    x += photoWidth
    photoWidth  = CollageSize.width() / 2
    photoHeight =  CollageSize.height() / 2
    for y in range(0, 2):
        scene.addPhoto(QRect(x, y * photoHeight, photoWidth, photoHeight), f.next())
   # Third column
    x += photoWidth
    photoWidth  = CollageSize.width() / 4
    photoHeight =  CollageSize.height() / 3
    for y in range(0, 3):
        scene.addPhoto(QRect(x, y * photoHeight, photoWidth, photoHeight), f.next())


def create_2_2B_2_collage(scene):
    f = LoopIter(filenames)
    # First column
    x = 0
    photoWidth  = CollageSize.width() / 4
    photoHeight =  CollageSize.height() / 2
    for y in range(0, 2):
        scene.addPhoto(QRect(x, y * photoHeight, photoWidth, photoHeight), f.next())
    # Second column
    x += photoWidth
    photoWidth  = CollageSize.width() / 2
    photoHeight =  CollageSize.height() / 2
    for y in range(0, 2):
        scene.addPhoto(QRect(x, y * photoHeight, photoWidth, photoHeight), f.next())
    # Third column
    x += photoWidth
    photoWidth  = CollageSize.width() / 4
    photoHeight =  CollageSize.height() / 2
    for y in range(0, 2):
        scene.addPhoto(QRect(x, y * photoHeight, photoWidth, photoHeight), f.next())


def createGridCollage(scene, numx , numy):
    f = LoopIter(filenames)
    photoWidth  = CollageSize.width() / numx
    photoHeight =  CollageSize.height() / numy
    for x in range(0, numx):
        for y in range(0, numy):
            scene.addPhoto(QRect(x * photoWidth, y * photoHeight, photoWidth, photoHeight), f.next())


def create_3x3_collage(scene):
    createGridCollage(scene, 3, 3)


def create_2x2_collage(scene):
    createGridCollage(scene, 2, 2)


def create_3x4_collage(scene):
    createGridCollage(scene, 3, 4)


#-------------------------------------------------------------------------------
def usage():
    print('Usage: ' +  os.path.basename(sys.argv[0]) + \
          'image1...imageN')
    print("\nOptions:\n")
    print("  -h         This help message")
    print("\nCommands:\n")
    for cmd, desc in HelpCommands:
        print('  %-16s  %s' % (cmd, desc))

#-------------------------------------------------------------------------------
def parse_args():
    try:
        opts, args = getopt.getopt(sys.argv[1:], 'h', ['help'])
    except getopt.GetoptError as err:
        logger.error(str(err))
        self.usage()
        sys.exit(1)

    for o, a in opts:
        if o == '-h' or o == '--help':
            usage()
            sys.exit(0)

    if len(args) == 0:
        logger.error('At least one file must be specified on the command line')
        usage()
        sys.exit(1)

    for f in args:
        filenames.append(os.path.abspath(f))
        logger.debug(str(filenames))


#-------------------------------------------------------------------------------
def main():
    global app
    # Parse arguments
    parse_args()

    # Create an PyQt5 application object.
    app = QApplication(sys.argv)

    # The QWidget widget is the base class of all user interface objects in PyQt5.
    w = QWidget()

    # Set window title
    w.setWindowTitle("PyView")
    w.resize(800, 800 * CollageAspectRatio)
    layout = QHBoxLayout()
    w.setLayout(layout)

    # Create GraphicsView
    gfxview = ImageView()
    layout.addWidget(gfxview)
    gfxview.setBackgroundBrush(QBrush(Qt.white))

    # Set OpenGL renderer
    if OpenGLRender:
        gfxview.setViewport(QOpenGLWidget())

    # Add scene
    scene = CollageScene()

    # Load pixmap and add it to the scene
    #create_3_2B_3_collage()
    #create_2_2B_2_collage()
    #create_3x3_collage()
    #create_2x2_collage()
    #createGridCollage(2, 3)
    create_3x4_collage(scene)

    gfxview.setScene(scene)

    # Show window
    w.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
