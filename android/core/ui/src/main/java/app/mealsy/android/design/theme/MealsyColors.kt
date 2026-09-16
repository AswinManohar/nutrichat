package app.mealsy.android.design.theme

import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

/**
 * The full Mealsy brand color palette for one theme (light or dark).
 *
 * Values are pulled verbatim from the design handoff
 * (`android/design-handoff/Mealsy Design System.html`) — never round, blend,
 * or otherwise "improve" these hex values. See `android/CLAUDE.md` for the
 * usage rules (one olive element per screen, pastels for icon chips/tags
 * only, no shadows except the FAB, no pure white/black).
 *
 * @property canvas Screen background everywhere.
 * @property surface Cards, list containers, coach notes, coach chat bubble.
 * @property surfacePressed Pressed state of surface rows/cards.
 * @property divider Hairlines inside surface containers, section borders.
 * @property hairline Outlined buttons, inputs, chips, stepper borders.
 * @property ink Display text, primary buttons, count badges, bottom nav.
 * @property inkPressed Pressed primary button.
 * @property muted Labels, secondary text, eyebrows.
 * @property inactive Inactive nav icons, placeholders, chevrons, timestamps.
 * @property olive Hero status element (exactly ONE per screen), FAB, toggle-on,
 *   progress fill, sparkle icon.
 * @property oliveText Text on olive.
 * @property oliveTrack Progress track, "eaten" part of snack bar, totals strip.
 * @property olivePressed Pressed olive.
 * @property userBubble User chat bubble background.
 * @property userBubbleText Text on the user chat bubble.
 * @property butter Pastel chip fill.
 * @property butterText Text on the butter pastel.
 * @property pink Pastel chip fill.
 * @property pinkText Text on the pink pastel.
 * @property leaf Pastel chip fill.
 * @property leafText Text on the leaf pastel.
 * @property powder Pastel chip fill.
 * @property powderText Text on the powder pastel.
 * @property terracotta Destructive filled background.
 * @property terracottaText Text on terracotta.
 * @property terracottaOutlineText Destructive outlined-variant text color.
 * @property navBar Bottom nav background. Identical in both themes.
 * @property navActive Bottom nav active icon/label color. Identical in both themes.
 * @property navInactive Bottom nav inactive icon/label color.
 * @property navBorder Bottom nav top hairline border, if any.
 * @property fab FAB background. Identical in both themes.
 * @property fabIcon FAB icon color. Identical in both themes.
 * @property fabShadow The FAB's drop shadow color. The FAB is the ONLY
 *   element in the entire design allowed a shadow.
 * @property isDark Whether this instance represents the dark theme, so
 *   components can branch where the design genuinely differs between modes.
 */
@Immutable
class MealsyColors(
    val canvas: Color,
    val surface: Color,
    val surfacePressed: Color,
    val divider: Color,
    val hairline: Color,
    val ink: Color,
    val inkPressed: Color,
    val muted: Color,
    val inactive: Color,
    val olive: Color,
    val oliveText: Color,
    val oliveTrack: Color,
    val olivePressed: Color,
    val userBubble: Color,
    val userBubbleText: Color,
    val butter: Color,
    val butterText: Color,
    val pink: Color,
    val pinkText: Color,
    val leaf: Color,
    val leafText: Color,
    val powder: Color,
    val powderText: Color,
    val terracotta: Color,
    val terracottaText: Color,
    val terracottaOutlineText: Color,
    val navBar: Color,
    val navActive: Color,
    val navInactive: Color,
    val navBorder: Color,
    val fab: Color,
    val fabIcon: Color,
    val fabShadow: Color,
    val isDark: Boolean,
)

/**
 * Builds the light-theme [MealsyColors], using the exact hex values from the
 * design handoff.
 */
fun lightMealsyColors(): MealsyColors = MealsyColors(
    canvas = Color(0xFFF6F1E1),
    surface = Color(0xFFEBE5D0),
    surfacePressed = Color(0xFFE2DBC4),
    divider = Color(0xFFDDD5BC),
    hairline = Color(0xFFC9C2A9),
    ink = Color(0xFF1C1B17),
    inkPressed = Color(0xFF3A3830),
    muted = Color(0xFF6F6A58),
    inactive = Color(0xFF8B887C),
    olive = Color(0xFFA6B565),
    oliveText = Color(0xFF2A3013),
    oliveTrack = Color(0xFFDEE2C3),
    olivePressed = Color(0xFF96A45B),
    userBubble = Color(0xFFDCE3BE),
    userBubbleText = Color(0xFF2A3013),
    butter = Color(0xFFF2D45C),
    butterText = Color(0xFF4A3A08),
    pink = Color(0xFFF0A9C6),
    pinkText = Color(0xFF5A1F3A),
    leaf = Color(0xFFA9C46F),
    leafText = Color(0xFF2A3013),
    powder = Color(0xFFA9C0E4),
    powderText = Color(0xFF1E3050),
    terracotta = Color(0xFFBE7250),
    terracottaText = Color(0xFF3F2012),
    terracottaOutlineText = Color(0xFFA85B3B),
    // Nav/FAB are frozen: identical in both light and dark per the design.
    navBar = Color(0xFF1C1B17),
    navActive = Color(0xFFF6F1E1),
    navInactive = Color(0xFF8B887C),
    navBorder = Color.Transparent,
    fab = Color(0xFFA6B565),
    fabIcon = Color(0xFF2A3013),
    // rgba(28,27,23,0.28) — the FAB is the ONLY element allowed a shadow.
    fabShadow = Color(0x471C1B17),
    isDark = false,
)

/**
 * Builds the dark-theme [MealsyColors].
 *
 * Most values come from the design handoff's dark token sheet. A handful of
 * tokens the dark sheet does not define are marked `Derived` below — those
 * are reasoned extrapolations, not spec values.
 */
fun darkMealsyColors(): MealsyColors = MealsyColors(
    canvas = Color(0xFF201F1A),
    surface = Color(0xFF2B2A23),
    // Derived: not in the design's dark sheet.
    surfacePressed = Color(0xFF35332A),
    divider = Color(0xFF3A382E),
    // Derived: not in the design's dark sheet.
    hairline = Color(0xFF4A4739),
    ink = Color(0xFFF6F1E1),
    // Derived: not in the design's dark sheet.
    inkPressed = Color(0xFFDDD5BC),
    muted = Color(0xFFA8A493),
    inactive = Color(0xFF7A776B),
    olive = Color(0xFF96A45B),
    oliveText = Color(0xFF1E230D),
    // Derived: not in the design's dark sheet.
    oliveTrack = Color(0xFF3C4327),
    // Derived: not in the design's dark sheet.
    olivePressed = Color(0xFF86944F),
    // Derived: not in the design's dark sheet.
    userBubble = Color(0xFF3A4226),
    // Derived: not in the design's dark sheet.
    userBubbleText = Color(0xFFDCE3BE),
    butter = Color(0xFFD9BE53),
    // Pastel TEXT colors stay at their light values in dark mode — the
    // pastel fills remain light enough for dark text.
    butterText = Color(0xFF4A3A08),
    pink = Color(0xFFD898B2),
    pinkText = Color(0xFF5A1F3A),
    leaf = Color(0xFF98B064),
    leafText = Color(0xFF2A3013),
    powder = Color(0xFF98ACCD),
    powderText = Color(0xFF1E3050),
    // Terracotta and its text stay at light values in dark mode per spec.
    terracotta = Color(0xFFBE7250),
    terracottaText = Color(0xFF3F2012),
    // Derived: not in the design's dark sheet.
    terracottaOutlineText = Color(0xFFC98363),
    // Nav/FAB are frozen: identical in both light and dark per the design.
    navBar = Color(0xFF1C1B17),
    navActive = Color(0xFFF6F1E1),
    navInactive = Color(0xFF7A776B),
    navBorder = Color(0xFF3A382E),
    fab = Color(0xFFA6B565),
    fabIcon = Color(0xFF2A3013),
    // rgba(28,27,23,0.28) — the FAB is the ONLY element allowed a shadow.
    fabShadow = Color(0x471C1B17),
    isDark = true,
)

/**
 * CompositionLocal providing the current [MealsyColors]. Defaults to the
 * light palette so previews and tests that skip [MealsyTheme] still render
 * sensibly; real screens always get this from [MealsyTheme].
 */
val LocalMealsyColors = staticCompositionLocalOf { lightMealsyColors() }
