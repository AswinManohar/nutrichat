package app.mealsy.android.ui.chat

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Matrix
import android.util.Log
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat

/**
 * Full-screen bottom sheet: requests camera permission, previews the live
 * feed via CameraX, captures a photo, then lets the user retake or accept it.
 * [onUsePhoto] receives the accepted [Bitmap]; [onDismiss] closes the sheet
 * without a result.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CameraSheet(onUsePhoto: (Bitmap) -> Unit, onDismiss: () -> Unit) {
    val context = LocalContext.current

    var hasPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    var permissionDenied by remember { mutableStateOf(false) }
    var captured by remember { mutableStateOf<Bitmap?>(null) }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { granted ->
        hasPermission = granted
        if (!granted) permissionDenied = true
    }

    LaunchedEffect(Unit) {
        if (!hasPermission) permissionLauncher.launch(Manifest.permission.CAMERA)
    }

    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier.fillMaxSize().padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            when {
                captured != null -> {
                    val bitmap = captured!!
                    Image(
                        bitmap = bitmap.asImageBitmap(),
                        contentDescription = "Captured meal photo",
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Row {
                        OutlinedButton(onClick = { captured = null }) {
                            Text("Retake")
                        }
                        Button(
                            onClick = { onUsePhoto(bitmap) },
                            modifier = Modifier.padding(start = 8.dp),
                        ) {
                            Text("Use photo")
                        }
                    }
                }

                hasPermission -> {
                    var imageCapture by remember { mutableStateOf<ImageCapture?>(null) }
                    CameraPreview(
                        modifier = Modifier.weight(1f).fillMaxWidth(),
                        onImageCaptureReady = { imageCapture = it },
                    )
                    Button(
                        onClick = {
                            imageCapture?.let { capture ->
                                takePhoto(context, capture) { bitmap -> captured = bitmap }
                            }
                        },
                        modifier = Modifier.padding(top = 8.dp),
                    ) {
                        Text("Capture")
                    }
                }

                permissionDenied -> {
                    Text(
                        "Mealsy needs camera access to snap a photo of your meal. " +
                            "You can grant it from the app's system settings.",
                    )
                    OutlinedButton(onClick = onDismiss, modifier = Modifier.padding(top = 8.dp)) {
                        Text("Close")
                    }
                }

                else -> {
                    // Waiting on the permission launcher's result.
                }
            }
        }
    }
}

@Composable
private fun CameraPreview(modifier: Modifier, onImageCaptureReady: (ImageCapture) -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val previewView = remember { PreviewView(context) }

    DisposableEffect(Unit) {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(context)
        cameraProviderFuture.addListener(
            {
                val cameraProvider = cameraProviderFuture.get()
                val preview = Preview.Builder().build().also {
                    it.setSurfaceProvider(previewView.surfaceProvider)
                }
                val imageCapture = ImageCapture.Builder().build()
                try {
                    cameraProvider.unbindAll()
                    cameraProvider.bindToLifecycle(
                        lifecycleOwner,
                        CameraSelector.DEFAULT_BACK_CAMERA,
                        preview,
                        imageCapture,
                    )
                    onImageCaptureReady(imageCapture)
                } catch (exc: Exception) {
                    Log.e("CameraSheet", "Failed to bind camera use cases", exc)
                }
            },
            ContextCompat.getMainExecutor(context),
        )
        onDispose {
            ProcessCameraProvider.getInstance(context).get().unbindAll()
        }
    }

    AndroidView(factory = { previewView }, modifier = modifier)
}

private fun takePhoto(
    context: android.content.Context,
    imageCapture: ImageCapture,
    onCaptured: (Bitmap) -> Unit,
) {
    imageCapture.takePicture(
        ContextCompat.getMainExecutor(context),
        object : ImageCapture.OnImageCapturedCallback() {
            override fun onCaptureSuccess(image: ImageProxy) {
                val bitmap = image.toBitmap()
                image.close()
                onCaptured(bitmap)
            }

            override fun onError(exception: ImageCaptureException) {
                Log.e("CameraSheet", "Photo capture failed", exception)
            }
        },
    )
}

/** Converts a JPEG/YUV [ImageProxy] frame into a correctly-rotated [Bitmap]. */
private fun ImageProxy.toBitmap(): Bitmap {
    val buffer = planes[0].buffer
    val bytes = ByteArray(buffer.remaining())
    buffer.get(bytes)
    val bitmap = android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
    val rotation = imageInfo.rotationDegrees
    if (rotation == 0) return bitmap
    val matrix = Matrix().apply { postRotate(rotation.toFloat()) }
    return Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
}
