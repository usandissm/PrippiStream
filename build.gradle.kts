// Plugin a livello di progetto (versioni: adegua a quelle del tuo Android Studio).
plugins {
    id("com.android.application") version "8.5.2" apply false
    // Kotlin 1.9.x: combinazione stabile con Chaquopy (Kotlin 2.0 dava l'errore friendPathsSet).
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
    id("com.chaquo.python") version "16.0.0" apply false
}
