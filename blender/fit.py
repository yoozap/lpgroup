# -*- coding: utf-8 -*-
"""Camera + massing solved from the reference photograph.

Method (see CAMERA_FIT.md):
  * roof silhouette traced by sky segmentation  -> two vanishing lines
  * loggia slab edges at x=820 give 60 px per storey
  * parked-car roof/wheel pairs give the horizon at y = 1660
  * perpendicularity of the two facade directions closes f
"""
import math

IMG_W, IMG_H = 2048, 1920
F_PX   = 1431.0         # focal length in pixels at IMG_W
PPY    = 1660.0         # principal point, pixels from the top edge
CAM_Z  = 1.65           # eye height, metres

# derived camera description
FULL_H   = 2.0 * PPY                                    # 3320
FOV_Y    = math.degrees(2.0 * math.atan(PPY / F_PX))    # 99.0 deg over FULL_H
ASPECT   = IMG_W / FULL_H
LENS_MM  = 36.0 * F_PX / IMG_W                          # 25.15 mm on 36 mm
SHIFT_Y  = (IMG_H / IMG_W) * (PPY / IMG_H - 0.5)   # Blender vertical rise

# block A, in Blender world space (Z up, camera at origin looking +Y)
A_ORIGIN = (-11.10, 70.32, 0.0)     # street/gable arris at pavement level (arris at u=797)
A_BEARING = 53.07      # deg about +Z; parapet line fits within 1.6 px over its length

SUN_ELEV = 58.0
SUN_AZI  = -30.6       # degrees in the Blender XY plane (sun behind-right of camera)

if __name__ == '__main__':
    print('lens  %.3f mm' % LENS_MM)
    print('shift_y %.6f' % SHIFT_Y)
    print('fov_y %.4f deg  aspect %.6f  fullH %.1f' % (FOV_Y, ASPECT, FULL_H))
    print('bearing %.4f' % A_BEARING)
