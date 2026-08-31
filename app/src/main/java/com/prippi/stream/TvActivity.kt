package com.prippi.stream

/**
 * Entry point dedicato al launcher Android TV. La UI resta adattiva e condivide
 * integralmente stato, motore, player e dati con l'attività mobile.
 */
class TvActivity : MainActivity() {
    override val forceTelevisionProfile: Boolean = true
}
