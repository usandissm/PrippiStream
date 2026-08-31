package com.prippi.stream.diagnostics

import org.junit.Test

/**
 * Dependency-free JVM test harness.
 *
 * The project currently has no unit-test framework dependency. Keeping these
 * checks self-contained lets them run with the Kotlin compiler without changing
 * the Gradle configuration.
 */
class DiagnosticSanitizerTest {
    @Test
    fun diagnosticSanitizerContract() {
        val cases = listOf(
            ::redactsAuthorizationAndBearerCredentials,
            ::redactsCookieHeadersAndStructuredCookies,
            ::redactsNamedSecretsAndSensitiveUrlParameters,
            ::redactsStandaloneJwt,
            ::redactsClearKeyAndDrmIdentifiers,
            ::redactsNetworkIdentifiersWhilePreservingPorts,
            ::keepsTimestampsAndOtherColonSeparatedDiagnostics,
            ::redactsUsernamesInWindowsAndUnixPaths,
            ::keepsUsefulDiagnosticContext,
            ::handlesRealisticMultilineReport,
            ::isIdempotent,
        )

        cases.forEach { it() }
    }

    private fun redactsAuthorizationAndBearerCredentials() {
        val input = """
            Authorization: Bearer live-access-token
            Proxy-Authorization: Basic dXNlcjpwYXNz
            headers={"Authorization":"Bearer json-token"}
            retry with bearer loose-token.value
        """.trimIndent()

        val sanitized = DiagnosticSanitizer.sanitize(input)

        assertNotContains(sanitized, "live-access-token")
        assertNotContains(sanitized, "dXNlcjpwYXNz")
        assertNotContains(sanitized, "json-token")
        assertNotContains(sanitized, "loose-token.value")
        assertContains(sanitized, "Authorization: Bearer [REDACTED]")
        assertContains(sanitized, "Proxy-Authorization: Basic [REDACTED]")
    }

    private fun redactsCookieHeadersAndStructuredCookies() {
        val input = """
            Cookie: sessionid=abc123; theme=dark
            Set-Cookie: auth=server-secret; Path=/; HttpOnly
            request={"cookie":"sid=inside-json; lang=it"}
        """.trimIndent()

        val sanitized = DiagnosticSanitizer.sanitize(input)

        assertNotContains(sanitized, "abc123")
        assertNotContains(sanitized, "server-secret")
        assertNotContains(sanitized, "inside-json")
        assertContains(sanitized, "Cookie: [REDACTED]")
        assertContains(sanitized, "Set-Cookie: [REDACTED]")
    }

    private fun redactsNamedSecretsAndSensitiveUrlParameters() {
        val input = """
            password="hunter2" api_key=mobile-key signature: signed-value
            session_id=install-session token='refresh-me'
            GET https://cdn.example/video.m3u8?quality=1080&token=url-token&sig=url-signature&lang=it
        """.trimIndent()

        val sanitized = DiagnosticSanitizer.sanitize(input)

        listOf(
            "hunter2",
            "mobile-key",
            "signed-value",
            "install-session",
            "refresh-me",
            "url-token",
            "url-signature",
        ).forEach { assertNotContains(sanitized, it) }
        assertContains(sanitized, "quality=1080")
        assertContains(sanitized, "lang=it")
        assertContains(sanitized, "cdn.example/video.m3u8")
    }

    private fun redactsStandaloneJwt() {
        val jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature_123"
        val sanitized = DiagnosticSanitizer.sanitize("decoder failed jwt=$jwt status=401")

        assertNotContains(sanitized, jwt)
        assertContains(sanitized, "jwt=[REDACTED]")
        assertContains(sanitized, "status=401")
    }

    private fun redactsClearKeyAndDrmIdentifiers() {
        val input = """
            drm={"kid":"0123456789abcdef","k":"fedcba9876543210","kty":"oct"}
            ClearKey=opaque-license-data drm_key=raw-drm-key kid=raw-kid
            DRM license key=contextual-key status=pending
            cache key=harmless-cache-key status=hit
        """.trimIndent()

        val sanitized = DiagnosticSanitizer.sanitize(input)

        listOf(
            "0123456789abcdef",
            "fedcba9876543210",
            "opaque-license-data",
            "raw-drm-key",
            "raw-kid",
            "contextual-key",
        ).forEach { assertNotContains(sanitized, it) }
        assertContains(sanitized, "\"kty\":\"oct\"")
        assertContains(sanitized, "\"kid\":\"[REDACTED]\"")
        assertContains(sanitized, "\"k\":\"[REDACTED]\"")
        assertContains(sanitized, "cache key=harmless-cache-key status=hit")
    }

    private fun redactsNetworkIdentifiersWhilePreservingPorts() {
        val input = """
            relay=172.20.10.11:18765 public=8.8.8.8
            ipv6=[2001:db8:85a3::8a2e:370:7334]:443 local=fe80::1%wlan0
            wifi_mac=AA:BB:CC:DD:EE:FF ethernet=00-11-22-33-44-55
        """.trimIndent()

        val sanitized = DiagnosticSanitizer.sanitize(input)

        listOf(
            "172.20.10.11",
            "8.8.8.8",
            "2001:db8:85a3::8a2e:370:7334",
            "fe80::1",
            "AA:BB:CC:DD:EE:FF",
            "00-11-22-33-44-55",
        ).forEach { assertNotContains(sanitized, it) }
        assertContains(sanitized, "[IP]:18765")
        assertContains(sanitized, "[IP]:443")
        assertContains(sanitized, "wifi_mac=[MAC]")
    }

    private fun keepsTimestampsAndOtherColonSeparatedDiagnostics() {
        val input = """
            2026-07-27T21:45:12.123+02:00 player_ready
            ratio=16:9 position=01:24:33
        """.trimIndent()

        val sanitized = DiagnosticSanitizer.sanitize(input)

        assertContains(sanitized, "21:45:12.123")
        assertContains(sanitized, "16:9")
        assertContains(sanitized, "01:24:33")
    }

    private fun redactsUsernamesInWindowsAndUnixPaths() {
        val input = """
            crash=C:\Users\Michele Santeramo\AppData\Local\Prippi\crash.log
            cache=C:/Users/michele/.cache/prippi/index.json
            linux=/home/michele/.local/share/prippi/report.txt
            mac=/Users/Michele/Library/Logs/PrippiStream.log
        """.trimIndent()

        val sanitized = DiagnosticSanitizer.sanitize(input)

        assertNotContains(sanitized, "Michele Santeramo")
        assertNotContains(sanitized, "/home/michele/")
        assertNotContains(sanitized, "/Users/Michele/")
        assertContains(sanitized, "C:\\Users\\[USER]")
        assertContains(sanitized, "C:/Users/[USER]")
        assertContains(sanitized, "/home/[USER]/")
        assertContains(sanitized, "/Users/[USER]/")
    }

    private fun keepsUsefulDiagnosticContext() {
        val input = """
            2026-07-27T22:07:10.778+02:00 ERROR PlayerActivity decoder_init_failed codec=audio/mp4a-latm status=500
            GET https://cdn.example/live/master.m3u8?quality=720&lang=it
            memory java_used_mb=36 java_max_mb=128 native_mb=32
        """.trimIndent()

        val sanitized = DiagnosticSanitizer.sanitize(input)

        assertContains(sanitized, "2026-07-27T22:07:10.778+02:00")
        assertContains(sanitized, "PlayerActivity")
        assertContains(sanitized, "decoder_init_failed")
        assertContains(sanitized, "codec=audio/mp4a-latm")
        assertContains(sanitized, "status=500")
        assertContains(sanitized, "quality=720&lang=it")
        assertContains(sanitized, "java_used_mb=36")
    }

    private fun handlesRealisticMultilineReport() {
        val input = """
            PrippiStream diagnostics
            session=3ec2d4ec-97f1-4fd0-9b85-50b977020183
            2026-07-27T22:07:10.778+02:00 playback_open url=https://video.example/a.m3u8?token=abc&quality=1080
            headers={"User-Agent":"PrippiStream/0.9.2","Cookie":"sid=secret","Authorization":"Bearer auth-secret"}
            drm={"kid":"kid-secret","k":"key-secret"}
            device ip=192.168.1.44 mac=DE:AD:BE:EF:00:01
            java.lang.IllegalStateException: Release should only be called once
                at com.prippi.stream.PlayerActivity(C:\Users\tester\PrippiStream\PlayerActivity.kt:846)
        """.trimIndent()

        val sanitized = DiagnosticSanitizer.sanitize(input)

        listOf(
            "3ec2d4ec-97f1-4fd0-9b85-50b977020183",
            "token=abc",
            "sid=secret",
            "auth-secret",
            "kid-secret",
            "key-secret",
            "192.168.1.44",
            "DE:AD:BE:EF:00:01",
            "\\tester\\",
        ).forEach { assertNotContains(sanitized, it) }
        assertContains(sanitized, "PrippiStream/0.9.2")
        assertContains(sanitized, "quality=1080")
        assertContains(sanitized, "Release should only be called once")
        assertContains(sanitized, "PlayerActivity.kt:846")
    }

    private fun isIdempotent() {
        val input = """
            Authorization: Bearer secret
            Cookie: sid=secret
            url=https://example.test/v.m3u8?token=secret&quality=1080
            host=10.0.0.8 mac=AA:BB:CC:DD:EE:FF
            path=C:\Users\Michele\report.log
            drm={"kid":"secret-kid","k":"secret-key"}
        """.trimIndent()

        val once = DiagnosticSanitizer.sanitize(input)
        val twice = DiagnosticSanitizer.sanitize(once)

        assertEquals(once, twice)
    }

    private fun assertContains(actual: String, expected: String) {
        if (!actual.contains(expected)) {
            throw AssertionError("Expected <$expected> in:\n$actual")
        }
    }

    private fun assertNotContains(actual: String, forbidden: String) {
        if (actual.contains(forbidden)) {
            throw AssertionError("Did not expect <$forbidden> in:\n$actual")
        }
    }

    private fun assertEquals(expected: String, actual: String) {
        if (expected != actual) {
            throw AssertionError("Values differ.\nExpected:\n$expected\nActual:\n$actual")
        }
    }
}
