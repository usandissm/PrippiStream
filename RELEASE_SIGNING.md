# Firma delle release Android

La prima release usa `prippistream-release.jks` e il file locale
`keystore.properties`. Entrambi sono esclusi da Git.

Questi due file devono essere conservati insieme in un backup sicuro: tutte le
versioni future devono usare la stessa chiave, altrimenti Android non potrà
installare gli aggiornamenti sopra l'app esistente.

Build ripetibile:

```powershell
./gradlew :app:assembleRelease
```

L'APK firmato viene generato in
`app/build/outputs/apk/release/app-release.apk`. Prima di pubblicarlo bisogna
verificare firma, `versionCode`, installazione e avvio sul dispositivo.

Nota per il primo passaggio dalla build di sviluppo: la build debug installata
sul telefono usa una firma diversa. Va disinstallata una sola volta prima di
installare la prima release ufficiale; dalle release successive funzionerà
l'aggiornamento in-place.

## Continuità mobile/TV

Il profilo Android TV/Google TV/box fa parte della stessa app
`com.prippi.stream`: non deve usare un package, una chiave o un canale di
aggiornamento separato. Le varianti ABI (`arm64-v8a`, `x86_64`,
`armeabi-v7a`) devono essere firmate con lo stesso certificato e mantenere un
`versionCode` coerente, così telefono, tablet e TV restano sullo stesso prodotto
e conservano dati e download negli aggiornamenti in-place.
