pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
        // Repository del plugin Chaquopy
        maven { url = uri("https://chaquo.com/maven") }
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "PrippiStreamApp"
include(":app")
