package app.mealsy.data.image

import android.graphics.Bitmap
import android.graphics.Matrix
import android.util.Base64
import java.io.ByteArrayOutputStream
import kotlin.math.roundToInt

/**
 * Turns a captured photo into the raw base64 payload the backend's
 * `POST /meals/log` expects in `image_b64` (see docs/reference/mobile-api.md)
 * — no data-URI prefix, since the backend decodes the string directly as
 * JPEG bytes.
 */
object ImageEncoder {

    /** Longest edge a bitmap is downscaled to before JPEG encoding. */
    private const val MAX_DIMENSION_PX = 1024

    private const val JPEG_QUALITY = 80

    /**
     * Encodes [bitmap] as base64 JPEG.
     *
     * Downscales so the longest edge is at most [MAX_DIMENSION_PX], preserving
     * aspect ratio; never upscales a bitmap that is already smaller. Encodes
     * at JPEG quality [JPEG_QUALITY] and returns the result as base64 with
     * [Base64.NO_WRAP] (single line, no trailing newline) and no `data:` URI
     * prefix.
     */
    fun encode(bitmap: Bitmap): String {
        val scaled = downscale(bitmap)
        val output = ByteArrayOutputStream()
        scaled.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, output)
        return Base64.encodeToString(output.toByteArray(), Base64.NO_WRAP)
    }

    /**
     * Rotates [bitmap] clockwise by [degrees] (as reported by CameraX's
     * `ImageInfo.rotationDegrees`). A pure, testable extraction of the
     * matrix math a camera capture path applies before downscaling —
     * CameraX itself isn't exercisable under Robolectric, but this part of
     * the pipeline is.
     */
    fun rotate(bitmap: Bitmap, degrees: Int): Bitmap {
        if (degrees % 360 == 0) return bitmap
        val matrix = Matrix().apply { postRotate(degrees.toFloat()) }
        return Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
    }

    private fun downscale(bitmap: Bitmap): Bitmap {
        val longestEdge = maxOf(bitmap.width, bitmap.height)
        if (longestEdge <= MAX_DIMENSION_PX) return bitmap

        val scale = MAX_DIMENSION_PX.toDouble() / longestEdge
        val targetWidth = (bitmap.width * scale).roundToInt().coerceAtLeast(1)
        val targetHeight = (bitmap.height * scale).roundToInt().coerceAtLeast(1)
        return Bitmap.createScaledBitmap(bitmap, targetWidth, targetHeight, true)
    }
}
