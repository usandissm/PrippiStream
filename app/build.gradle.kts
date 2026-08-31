// ────────────────────────────────────────────────────────────────────────────
// App PrippiStream (Android nativo). Chaquopy fa girare il MOTORE Python
// (src/main/python: bridge.py + engine/ + xbmc_shim/), la UI è Compose, il
// player è Media3/ExoPlayer.
// NB: adegua le versioni (AGP/Kotlin/Compose/Chaquopy/Media3) a quelle installate
//     nel tuo Android Studio — qui ci sono valori recenti ragionevoli.
// ────────────────────────────────────────────────────────────────────────────
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

val releaseKeystoreFile = rootProject.file("keystore.properties")
val releaseKeystore = Properties().apply {
    if (releaseKeystoreFile.isFile) {
        releaseKeystoreFile.inputStream().use(::load)
    }
}
val prippiAbis = providers.gradleProperty("prippiAbis")
    .orNull
    ?.split(',')
    ?.map(String::trim)
    ?.filter(String::isNotEmpty)
    ?.takeIf(List<String>::isNotEmpty)
    ?: listOf("armeabi-v7a", "arm64-v8a")
val diagnosticsRelayUrl = providers.gradleProperty("prippiDiagnosticsRelayUrl")
    .orElse(providers.environmentVariable("PRIPPI_DIAGNOSTICS_RELAY_URL"))
    .getOrElse("")
    .replace("\\", "\\\\")
    .replace("\"", "\\\"")
val requireDiagnosticsRelay = providers.gradleProperty("prippiRequireDiagnosticsRelay")
    .orElse(providers.environmentVariable("PRIPPI_REQUIRE_DIAGNOSTICS_RELAY"))
    .map { it.equals("true", ignoreCase = true) }
    .getOrElse(false)

if (requireDiagnosticsRelay && diagnosticsRelayUrl.isBlank()) {
    throw GradleException(
        "La build richiede il relay diagnostico, ma PRIPPI_DIAGNOSTICS_RELAY_URL non è configurato.",
    )
}

android {
    namespace = "com.prippi.stream"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.prippi.stream"
        minSdk = 24
        targetSdk = 34
        versionCode = 72
        versionName = "0.9.17"
        buildConfigField("String", "DIAGNOSTICS_RELAY_URL", "\"$diagnosticsRelayUrl\"")

        // Release universale per box Android 32-bit e dispositivi ARM64.
        // `-PprippiAbis=x86_64` produce una build separata per l'emulatore.
        ndk { abiFilters += prippiAbis }
    }

    signingConfigs {
        if (releaseKeystoreFile.isFile) {
            create("release") {
                storeFile = rootProject.file(releaseKeystore.getProperty("storeFile"))
                storePassword = releaseKeystore.getProperty("storePassword")
                keyAlias = releaseKeystore.getProperty("keyAlias")
                keyPassword = releaseKeystore.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        getByName("release") {
            signingConfig = signingConfigs.findByName("release")
            isMinifyEnabled = false
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }

    // Compose compiler abbinato a Kotlin 1.9.24 (con Kotlin 1.9 si usa questo,
    // non il plugin compose che serve solo a Kotlin 2.0).
    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.14"
    }

    // Chaquopy prende automaticamente src/main/python come sorgente Python.
    packaging {
        resources.excludes += setOf("META-INF/*", "**/*.md", "**/*.txt")
    }
}

// Config Chaquopy (Kotlin DSL): blocco separato, NON dentro android.defaultConfig.
chaquopy {
    defaultConfig {
        version = "3.11"     // versione Python (supportata da Chaquopy)
        pip {
            install("requests")
            install("pycryptodome")   // AES veloce -> download rapidi (download_crypto lo preferisce)
            install("Pillow")         // decodifica il captcha WebP corrente di Maxstream/uprot
        }
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.06.00")
    implementation(composeBom)
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.core:core-splashscreen:1.0.1")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.6")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.6")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.8.6")
    implementation("androidx.work:work-runtime-ktx:2.9.1")
    implementation("io.coil-kt:coil-compose:2.7.0")   // poster async

    // Player nativo
    val media3 = "1.4.1"
    implementation("androidx.media3:media3-exoplayer:$media3")
    implementation("androidx.media3:media3-exoplayer-hls:$media3")
    implementation("androidx.media3:media3-exoplayer-dash:$media3")
    implementation("androidx.media3:media3-ui:$media3")
    implementation("androidx.media3:media3-session:$media3")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
