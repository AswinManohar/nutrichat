package app.mealsy.android.ui.profile

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import app.mealsy.android.R
import app.mealsy.android.design.theme.mealsyScreenPadding
import app.mealsy.android.ui.common.ErrorKind
import app.mealsy.android.ui.common.ErrorState
import app.mealsy.android.ui.common.LoadingState
import app.mealsy.android.ui.settings.HeaderRow
import app.mealsy.data.repo.ProfileUnavailableException
import kotlinx.coroutines.CancellationException
import java.io.IOException
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

/** Rendering state of a read-only profile sub-screen. [Error.message] is the server's text for a 503. */
sealed interface LoadState<out T> {
    data object Loading : LoadState<Nothing>

    data class Error(val kind: ErrorKind, val message: String? = null) : LoadState<Nothing>

    data class Loaded<T>(val data: T) : LoadState<T>
}

/** Runs [block] and maps its outcome (and the failure kinds the profile endpoints produce) to a [LoadState]. */
internal suspend fun <T> loadState(block: suspend () -> T): LoadState<T> =
    try {
        LoadState.Loaded(block())
    } catch (exc: CancellationException) {
        throw exc
    } catch (exc: ProfileUnavailableException) {
        LoadState.Error(ErrorKind.LoadFailed, exc.message?.ifBlank { null })
    } catch (exc: IOException) {
        LoadState.Error(ErrorKind.Offline)
    } catch (exc: Exception) {
        LoadState.Error(ErrorKind.LoadFailed)
    }

/** An ISO timestamp as a medium local date, or null when absent or unparseable. */
internal fun formatDate(iso: String?): String? =
    iso?.let { runCatching { OffsetDateTime.parse(it) }.getOrNull() }
        ?.atZoneSameInstant(ZoneId.systemDefault())
        ?.toLocalDate()
        ?.format(DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM))

/** Back header, [title], then loading / error / [content] for a [LoadState]. */
@Composable
internal fun <T> LoadStateScreen(
    title: String,
    state: LoadState<T>,
    loadingText: String,
    errorText: String,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.(T) -> Unit,
) {
    Column(modifier = modifier.verticalScroll(rememberScrollState()).mealsyScreenPadding()) {
        HeaderRow(title = title, onBack = onBack)
        Spacer(modifier = Modifier.height(20.dp))
        when (state) {
            LoadState.Loading -> LoadingState(loadingText, Modifier.height(240.dp))
            is LoadState.Error ->
                ErrorState(
                    message =
                        state.message
                            ?: if (state.kind == ErrorKind.Offline) stringResource(R.string.error_offline) else errorText,
                    onRetry = onRetry,
                    modifier = Modifier.height(240.dp),
                )
            is LoadState.Loaded -> content(state.data)
        }
    }
}
