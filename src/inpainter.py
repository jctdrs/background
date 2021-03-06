import numpy as np
import matplotlib.pyplot as plt
import cv2
import math
import time
import pickle

class Inpainter(object):
    inputImage = None
    mask = updatedMask = None
    result = None
    workImage = None
    sourceRegion = None
    targetRegion = None
    originalSourceRegion = None
    gradientX = None
    gradientY = None
    confidence = None
    data = None
    LAPLACIAN_KERNEL = NORMAL_KERNELX = NORMAL_KERNELY = None
    bestMatchUpperLeft = bestMatchLowerRight = None
    patchHeight = patchWidth = 0
    fillFront = []
    normals = []
    sourcePatchULList = []
    targetPatchSList = []
    targetPatchTList = []
    halfPatchWidth = None
    targetIndex = None

    def __init__(self, inputImage, mask, crop_originalImage, crop_inpaintMask,  halfPatchWidth, select):
        self.select = select
        if select == 1:
            self.nonCrop = np.copy(inputImage)
            self.mask = np.copy(np.uint8(crop_inpaintMask))
            self.inputImage = crop_originalImage
        elif self.select == 0:
            self.inputImage = inputImage
            self.mask = np.copy(np.uint8(mask))

        self.updatedMask = np.copy(self.mask)
        self.workImage = np.copy(self.inputImage)
        self.result = np.ndarray(shape=inputImage.shape, dtype=inputImage.dtype)
        self.halfPatchWidth = halfPatchWidth

    def inpaint(self, file_name, directory_2, yl, xr):
        self.initializeMats()
        self.calculateGradients()
        stay = True
        k = 0
        PositionTrack_dict = {}
        while stay:
            k += 1
            start = time.time()
            self.computeFillFront()
            self.computeConfidence()
            self.computeData()
            self.computeTarget()
            self.computeBestPatch()
            PositionTrack_image, PositionTrack_dict = self.updateMats(PositionTrack_dict, yl, xr)
            stay = self.checkEnd()
            end = time.time()
            cv2.imwrite(directory_2+'/updatedMask/updatedMask_%.2d.png'%k, self.updatedMask)
            if self.select == 1:
                cv2.imwrite(directory_2+'/iterations/inpaintedImage_%.2d.png'%k, self.nonCrop)
            elif self.select == 0:
                cv2.imwrite(directory_2+'/iterations/inpaintedImage_%.2d.png'%k, self.workImage)
            cv2.imwrite(directory_2+'/positionTrack/positionTrack_%.2d.png'%k, PositionTrack_image)
            print 'Iteration '+str(k)+' -- '+str(np.round(end-start,2))+' sec'+' '+str(self.halfPatchWidth)
        if self.select == 1:
            self.result = np.copy(self.nonCrop)
        else:
            self.result = np.copy(self.workImage)
        file_path = directory_2+'/positionTrack'
        name = 'PositionTrack_dict.pkl'
        pickle.dump(PositionTrack_dict, open(file_path+'/'+name, 'wb'), pickle.HIGHEST_PROTOCOL)

    def initializeMats(self):
        _, self.confidence = cv2.threshold(self.mask, 10, 255, cv2.THRESH_BINARY)
        _, self.confidence = cv2.threshold(self.confidence, 2, 1, cv2.THRESH_BINARY_INV)
        self.sourceRegion  = np.copy(self.confidence)
        self.originalSourceRegion = np.copy(self.sourceRegion)
        self.confidence = np.float32(self.confidence)
        _, self.targetRegion = cv2.threshold(self.mask, 10 , 255, cv2.THRESH_BINARY)
        _, self.targetRegion = cv2.threshold(self.targetRegion, 2, 1, cv2.THRESH_BINARY)
        self.data = np.ndarray(shape=self.inputImage.shape[:2], dtype=np.float32)
        self.LAPLACIAN_KERNEL = np.ones((3, 3), dtype = np.float32)
        self.LAPLACIAN_KERNEL[1, 1] = -8
        self.NORMAL_KERNELX = np.zeros((3, 3), dtype = np.float32)
        self.NORMAL_KERNELX[1, 0] = -1
        self.NORMAL_KERNELX[1, 2] = 1
        self.NORMAL_KERNELY = cv2.transpose(self.NORMAL_KERNELX)

    def calculateGradients(self):
        srcGray = self.workImage
        self.gradientX = cv2.Scharr(srcGray, cv2.CV_32F, 1, 0)
        self.gradientX = cv2.convertScaleAbs(self.gradientX)
        self.gradientX = np.float32(self.gradientX)
        self.gradientY = cv2.Scharr(srcGray, cv2.CV_32F, 0, 1)
        self.gradientY = cv2.convertScaleAbs(self.gradientY)
        self.gradientY = np.float32(self.gradientY)

        height, width = self.sourceRegion.shape
        for y in range(height):
            for x in range(width):
                if self.sourceRegion[y, x] == 0:
                    self.gradientX[y, x] = 0
                    self.gradientY[y, x] = 0

        self.gradientX /= 2**16-1
        self.gradientY /= 2**16-1

    def computeFillFront(self):
        boundryMat = cv2.filter2D(self.targetRegion, cv2.CV_32F, self.LAPLACIAN_KERNEL)
        sourceGradientX = cv2.filter2D(self.sourceRegion, cv2.CV_32F, self.NORMAL_KERNELX)
        sourceGradientY = cv2.filter2D(self.sourceRegion, cv2.CV_32F, self.NORMAL_KERNELY)
        del self.fillFront[:]
        del self.normals[:]
        height, width = boundryMat.shape[:2]
        for y in range(height):
            for x in range(width):
                if boundryMat[y, x] > 0:
                    self.fillFront.append((x, y))
                    dx = sourceGradientX[y, x]
                    dy = sourceGradientY[y, x]

                    normalX, normalY = dy, - dx
                    tempF = math.sqrt(pow(normalX, 2) + pow(normalY, 2))
                    if not tempF == 0:
                        normalX /= tempF
                        normalY /= tempF
                    self.normals.append((normalX, normalY))

    def getPatch(self, point):
        centerX, centerY = point
        height, width = self.workImage.shape[:2]
        minX = max(centerX - self.halfPatchWidth, 0)
        maxX = min(centerX + self.halfPatchWidth, width - 1)
        minY = max(centerY - self.halfPatchWidth, 0)
        maxY = min(centerY + self.halfPatchWidth, height - 1)
        upperLeft = (minX, minY)
        lowerRight = (maxX, maxY)
        return upperLeft, lowerRight

    def computeConfidence(self):
        for p in self.fillFront:
            pX, pY = p
            (aX, aY), (bX, bY) = self.getPatch(p)
            total = 0
            for y in range(aY, bY + 1):
                for x in range(aX, bX + 1):
                    if self.targetRegion[y, x] == 0:
                        total += self.confidence[y, x]
            self.confidence[pY, pX] = total / ((bX-aX+1) * (bY-aY+1))

    def computeData(self):
        for i in range(len(self.fillFront)):
            x, y = self.fillFront[i]
            currentNormalX, currentNormalY = self.normals[i]
            self.data[y, x] = math.fabs(self.gradientX[y, x] * currentNormalX + self.gradientY[y, x] * currentNormalY) + 0.00001

    def computeTarget(self):
        self.targetIndex = 0
        maxPriority, priority = 0, 0
        omega, alpha, beta = 0.7, 0.2, 0.8
        for i in range(len(self.fillFront)):
            x, y = self.fillFront[i]
            Rcp = (1-omega) * self.confidence[y, x] + omega
            priority = alpha * Rcp + beta * self.data[y, x]
            if False:
                priority = self.confidence[y, x] * self.data[y, x]

            if priority > maxPriority:
                maxPriority = priority
                self.targetIndex = i

    def computeBestPatch(self):
        minError = bestPatchVariance = 9999999999999999
        currentPoint = self.fillFront[self.targetIndex]
        (aX, aY), (bX, bY) = self.getPatch(currentPoint)
        pHeight, pWidth = bY - aY + 1, bX - aX + 1
        height, width = self.workImage.shape[:2]
        workImage = self.workImage.tolist()

        if pHeight != self.patchHeight or pWidth != self.patchWidth:
            self.patchHeight, self.patchWidth = pHeight, pWidth
            area = pHeight * pWidth
            SUM_KERNEL = np.ones((pHeight, pWidth), dtype = np.uint16)
            convolvedMat = cv2.filter2D(self.originalSourceRegion, cv2.CV_16U, SUM_KERNEL, anchor = (0, 0))
            self.sourcePatchULList = []

            for y in range(height - pHeight):
                for x in range(width - pWidth):
                    if convolvedMat[y, x] == area:
                        self.sourcePatchULList.append((y, x))

        countedNum = 0
        self.targetPatchSList = []
        self.targetPatchTList = []

        for i in range(pHeight):
            for j in range(pWidth):
                if self.sourceRegion[aY+i, aX+j] == 1:
                    countedNum += 1
                    self.targetPatchSList.append((i, j))
                else:
                    self.targetPatchTList.append((i, j))


        for (y, x) in self.sourcePatchULList[:int(np.floor(len(self.sourcePatchULList)*1))]:
                patchError = 0
                mean = 0
                skipPatch = False

                for (i, j) in self.targetPatchSList:
                        sourcePixel = workImage[y+i][x+j]
                        targetPixel = workImage[aY+i][aX+j]

                        difference = float(sourcePixel) - float(targetPixel)
                        patchError += math.pow(difference, 2)
                        mean += sourcePixel

                countedNum = float(countedNum)
                patchError /= countedNum
                mean /= countedNum

                alpha, beta = 0.9, 0.5 #0.9, 0.5
                if alpha * patchError <= minError:
                    patchVariance = 0

                    for (i, j) in self.targetPatchTList:
                                sourcePixel = workImage[y+i][x+j]
                                difference = sourcePixel - mean
                                patchVariance += math.pow(difference, 2)

                    if patchError < alpha * minError or patchVariance < beta * bestPatchVariance:
                        bestPatchVariance = patchVariance
                        minError = patchError
                        self.bestMatchUpperLeft = (x, y)
                        self.bestMatchLowerRight = (x+pWidth-1, y+pHeight-1)

    def updateMats(self, PositionTrack_dict, yl, xr):
        targetPoint = self.fillFront[self.targetIndex]
        tX, tY = targetPoint
        (aX, aY), (bX, bY) = self.getPatch(targetPoint)
        bulX, bulY = self.bestMatchUpperLeft
        pHeight, pWidth = bY-aY+1, bX-aX+1
        PositionTrack_image = np.copy(self.updatedMask)
        for (i, j) in self.targetPatchTList:
            PositionTrack_image[bulY+i, bulX+j] = 255
            self.workImage[aY+i, aX+j] = self.workImage[bulY+i, bulX+j]
            if self.select == 1:
                self.nonCrop[aY+i+yl, aX+j+xr] = self.workImage[bulY+i, bulX+j]
            self.gradientX[aY+i, aX+j] = self.gradientX[bulY+i, bulX+j]
            self.gradientY[aY+i, aX+j] = self.gradientY[bulY+i, bulX+j]
            self.confidence[aY+i, aX+j] = self.confidence[tY, tX]
            self.sourceRegion[aY+i, aX+j] = 1
            self.targetRegion[aY+i, aX+j] = 0
            self.updatedMask[aY+i, aX+j] = 0
            PositionTrack_dict[(aY+i, aX+j)] = (bulY+i, bulX+j)

        return PositionTrack_image, PositionTrack_dict

    def checkEnd(self):
        height, width = self.sourceRegion.shape[:2]
        for y in range(height):
            for x in range(width):
                if self.sourceRegion[y, x] == 0:
                    return True
        return False
