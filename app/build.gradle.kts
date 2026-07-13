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
    id("org.jetbrains.kotlin.plugin.compose")
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

        python {
            // Deve combaciare con una versione supportata da Chaquopy (3.8–3.12).
            version = "3.11"
            pip {
                // Dipendenze native/veloci prese da pip (Chaquopy ha i wheel):
                install("requests")
                install("pycryptodome")   // ← rende i download veloci (download_crypto lo preferisce)
                // cloudscraper e altre le abbiamo già in engine/lib/, ma se preferisci pip:
                // install("cloudscraper")
            }
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

    // Chaquopy prende automaticamente src/main/python come sorgente Python.
    packaging {
        resources.excludes += setOf("META-INF/*", "**/*.md", "**/*.txt")
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.09.00")
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
