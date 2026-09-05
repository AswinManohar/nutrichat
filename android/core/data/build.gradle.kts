import java.util.Properties

plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.ksp)
    alias(libs.plugins.hilt.android)
}

// :core:data cannot see :app's BuildConfig, and ApiModule (Retrofit setup)
// lives here so it stays unit-testable with MockWebServer independent of the
// Android app module. Rather than route the base URL through a Hilt @Named
// provider :app would have to supply, this module reads the same
// local.properties key straight into its own BuildConfig field — both
// modules stay independently buildable/testable, and Task 5's app module
// needs no extra wiring to consume MealsyApi.
val localProperties = Properties().apply {
    val localPropertiesFile = rootProject.file("local.properties")
    if (localPropertiesFile.exists()) {
        localPropertiesFile.inputStream().use { load(it) }
    }
}

android {
    namespace = "app.mealsy.android.data"
    compileSdk = 35

    defaultConfig {
        minSdk = 26

        buildConfigField(
            "String",
            "API_BASE_URL",
            "\"${localProperties.getProperty("API_BASE_URL", "http://10.0.2.2:8000")}\"",
        )

        // Task 4: Supabase project URL/anon key, read the same way as
        // API_BASE_URL above — from local.properties, never hardcoded or
        // committed. Left blank by default; AuthModule's supabase client
        // creation fails loudly at Hilt injection time (not at compile
        // time) if these are unset, mirroring normalizeBaseUrl() below.
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
    }

    buildTypes {
        // Release must never silently inherit the debug/emulator default
        // ("http://10.0.2.2:8000"). If API_BASE_URL isn't set in
        // local.properties for a release build, this resolves to "" and
        // ApiModule.normalizeBaseUrl() throws IllegalStateException at
        // injection time instead of shipping a build that talks to the
        // emulator loopback address.
        release {
            buildConfigField(
                "String",
                "API_BASE_URL",
                "\"${localProperties.getProperty("API_BASE_URL", "")}\"",
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
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation(project(":core:domain"))

    implementation(libs.hilt.android)
    ksp(libs.hilt.compiler)

    implementation(libs.retrofit)
    implementation(libs.retrofit.kotlinx.serialization.converter)
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging.interceptor)
    implementation(libs.kotlinx.serialization.json)

    implementation(libs.room.runtime)
    implementation(libs.room.ktx)
    ksp(libs.room.compiler)

    implementation(libs.work.runtime.ktx)

    // `api`, not `implementation`: MainActivity (in :app) injects the
    // SupabaseClient directly to call handleDeeplinks(intent), so its type
    // needs to be on :app's compile classpath, not just :core:data's.
    api(platform(libs.supabase.bom))
    api(libs.supabase.gotrue)
    implementation(libs.supabase.postgrest)
    // supabase-kt's HTTP client is Ktor-based and needs an explicit engine;
    // OkHttp is already a dependency here (Retrofit's client) so reuse it
    // rather than pulling in a second HTTP stack (e.g. ktor-client-android).
    implementation(libs.ktor.client.okhttp)

    implementation(libs.kotlinx.coroutines.android)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.mockwebserver)
    testImplementation(libs.turbine)
    testImplementation(libs.robolectric)
}
