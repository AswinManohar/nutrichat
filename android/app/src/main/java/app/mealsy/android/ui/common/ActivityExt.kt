package app.mealsy.android.ui.common

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper

/**
 * Unwraps [ContextWrapper]s to the hosting [Activity], or null when there is none.
 *
 * Credential Manager needs an Activity to anchor its account-picker sheet. Composables
 * resolve it here from `LocalContext.current` and hand it to the ViewModel call, so a
 * ViewModel never stores an Activity.
 */
tailrec fun Context.findActivity(): Activity? =
    when (this) {
        is Activity -> this
        is ContextWrapper -> baseContext.findActivity()
        else -> null
    }
