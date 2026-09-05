import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.hilt.android)
    alias(libs.plugins.ksp)
    alias(libs.plugins.compose.compiler)
}

val localProperties = Properties().apply {
    val localPropertiesFile = rootProject.file("local.properties")
    if (localPropertiesFile.exists()) {
        localPropertiesFile.inputStream().use { load(it) }
    }
}

android {
    namespace = "app.mealsy.android"
    compileSdk = 35

    defaultConfig {
        applicationId = "app.mealsy.android"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        buildConfigField(
            "String",
            "API_BASE_URL",
            "\"${localProperties.getProperty("API_BASE_URL", "http://10.0.2.2:8000")}\"",
        )
        buildConfigField(
            "String",
            "SUPABASE_URL",
            "\"${localProperties.getProperty("SUPABASE_URL", "")}\"",
        )
        buildConfigField(
            "String",
            "SUPABASE_ANON_KEY",
            "\"${localProperties.getProperty("SUPABASE_ANON_KEY", "")}\"",
        )
        buildConfigField(
            "String",
            "PRIVACY_POLICY_URL",
            "\"${localProperties.getProperty("PRIVACY_POLICY_URL", "https://mealsy.app/privacy")}\"",
        )
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
}

// Crashlytics's Gradle plugin, like google-services above, needs
// google-services.json (it reads the Firebase app id out of it to upload
// mapping/build ids) — applied conditionally so the build still works on a
// checkout without Firebase configured yet (see Global Constraints).
if (file("google-services.json").exists()) {
    apply(plugin = "com.google.gms.google-services")
    apply(plugin = "com.google.firebase.crashlytics")
}

dependencies {
    implementation(project(":core:domain"))
    implementation(project(":core:data"))

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.navigation.compose)

    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.graphics)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
    debugImplementation(libs.compose.ui.tooling)

    implementation(libs.hilt.android)
    implementation(libs.hilt.navigation.compose)
    ksp(libs.hilt.compiler)

    implementation(libs.camerax.core)
    implementation(libs.camerax.camera2)
    implementation(libs.camerax.lifecycle)
    implementation(libs.camerax.view)

    implementation(libs.work.runtime.ktx)
    implementation(libs.androidx.hilt.work)

    // :core:data's Retrofit dependency is `implementation`-scoped there, so
    // it isn't on :app's compile classpath transitively — ChatViewModel
    // catches retrofit2.HttpException directly to distinguish server errors
    // from IOException (offline), so it needs its own reference here.
    implementation(libs.retrofit)

    implementation(platform(libs.firebase.bom))
    implementation(libs.firebase.messaging.ktx)
    // ErrorReporting no-ops (via FirebaseApp.getApps(context).isEmpty()) when
    // there's no google-services.json, same guard PushRegistrar's
    // FirebaseFcmTokenProvider uses — safe to depend on unconditionally even
    // though the Crashlytics *plugin* above is applied conditionally.
    implementation(libs.firebase.crashlytics.ktx)

    // PushRegistrar (Task 9) persists the last-sent FCM token here, mirroring
    // :core:data's ConversationIdStore pattern.
    implementation(libs.androidx.datastore.preferences)

    testImplementation(libs.junit)
    testImplementation(libs.turbine)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.mockwebserver)
    testImplementation(libs.retrofit)
    testImplementation(libs.retrofit.kotlinx.serialization.converter)
    testImplementation(libs.okhttp)
    testImplementation(libs.kotlinx.serialization.json)
    androidTestImplementation(libs.androidx.test.ext.junit)
    androidTestImplementation(libs.espresso.core)
}
