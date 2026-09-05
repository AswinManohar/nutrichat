package app.mealsy.data.image

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.util.Base64
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/** [ImageEncoder] against real Robolectric-backed [Bitmap]/JPEG codecs. */
@RunWith(RobolectricTestRunner::class)
class ImageEncoderTest {

    private fun solidBitmap(width: Int, height: Int): Bitmap {
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(Color.RED)
        return bitmap
    }

    private fun decodedDimensions(base64: String): Pair<Int, Int> {
        val bytes = Base64.decode(base64, Base64.NO_WRAP)
        val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        return bitmap.width to bitmap.height
    }

    @Test
    fun `encode caps longest edge at 1024`() {
        val bitmap = solidBitmap(2048, 1536)

        val encoded = ImageEncoder.encode(bitmap)

        val (width, height) = decodedDimensions(encoded)
        assertEquals(1024, maxOf(width, height))
        // Aspect ratio preserved: 2048x1536 -> 1024x768.
        assertEquals(768, minOf(width, height))
    }

    @Test
    fun `output decodes back to a JPEG`() {
        val bitmap = solidBitmap(512, 512)

        val encoded = ImageEncoder.encode(bitmap)

        assertTrue("base64 output should not be empty", encoded.isNotEmpty())
        val bytes = Base64.decode(encoded, Base64.NO_WRAP)
        val decoded = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        assertTrue("decoded bytes should be a valid bitmap", decoded != null)
        assertEquals(512, decoded.width)
        assertEquals(512, decoded.height)
    }

    @Test
    fun `already-small bitmap not upscaled`() {
        val bitmap = solidBitmap(200, 100)

        val encoded = ImageEncoder.encode(bitmap)

        val (width, height) = decodedDimensions(encoded)
        assertEquals(200, width)
        assertEquals(100, height)
    }

    @Test
    fun `rotate 90 degrees swaps width and height`() {
        val bitmap = solidBitmap(200, 100)

        val rotated = ImageEncoder.rotate(bitmap, 90)

        assertEquals(100, rotated.width)
        assertEquals(200, rotated.height)
    }

    @Test
    fun `rotate 0 degrees returns the same bitmap`() {
        val bitmap = solidBitmap(200, 100)

        val rotated = ImageEncoder.rotate(bitmap, 0)

        assertEquals(bitmap, rotated)
    }
}
