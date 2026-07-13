// ────────────────────────────────────────────────────────────────────────────
// App PrippiStream (Android nativo). Chaquopy fa girare il MOTORE Python
// (src/main/python: bridge.py + engine/ + xbmc_shim/), la UI è Compose, il
// player è Media3/ExoPlayer.
// NB: adegua le versioni (AGP/Kotlin/Compose/Chaquopy/Media3) a quelle installate
//     nel tuo Android Studio — qui ci sono valori recenti ragionevoli.
// ────────────────────────────────────────────────────────────────────────────
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "com.prippi.stream"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.prippi.stream"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.1-mvp"

        // Chaquopy: ABI del telefono (Samsung A16 = arm64). Aggiungi armeabi-v7a
        // per device vecchi. NON usare x86 salvo emulatore.
        ndk { abiFilters += listOf("arm64-v8a") }
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
        }
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.06.00")
    implementation(composeBom)
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.6")
    implementation("io.coil-kt:coil-compose:2.7.0")   // poster async

    // Player nativo
    val media3 = "1.4.1"
    implementation("androidx.media3:media3-exoplayer:$media3")
    implementation("androidx.media3:media3-exoplayer-hls:$media3")
    implementation("androidx.media3:media3-exoplayer-dash:$media3")
    implementation("androidx.media3:media3-ui:$media3")
}
