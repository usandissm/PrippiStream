package com.prippi.stream.diagnostics

/**
 * Removes credentials and personal network/device data from diagnostic text.
 *
 * The sanitizer deliberately keeps field names, URL structure, ports, log levels,
 * timestamps and error messages so that a report remains useful when debugging.
 * It is stateless, thread-safe and idempotent.
 */
object DiagnosticSanitizer {
    private const val SECRET = "[REDACTED]"
    private const val IP_ADDRESS = "[IP]"
    private const val MAC_ADDRESS = "[MAC]"
    private const val USERNAME = "[USER]"

    private val authorizationHeader = Regex(
        """(?im)^(\s*(?:Authorization|Proxy-Authorization)\s*:\s*)(?:(Bearer|Basic|Digest)\s+)?[^\r\n]*$""",
    )
    private val authorizationQuotedField = Regex(
        """(?i)(["']?(?:authorization|proxy-authorization)["']?\s*[:=]\s*)(["'])(?:(Bearer|Basic|Digest)\s+)?(.*?)\2""",
    )
    private val authorizationField = Regex(
        """(?i)(\b(?:authorization|proxy-authorization)\b\h*[:=]\h*+)(?!(?:(?:Bearer|Basic|Digest)\h+)?\[REDACTED])(?:(Bearer|Basic|Digest)\h+)?([^,\s;}]+)""",
    )
    private val bearerCredential = Regex(
        """(?i)\b(Bearer)\s+(?!\[REDACTED])([A-Za-z0-9._~+/=-]+)""",
    )

    private val cookieHeader = Regex(
        """(?im)^(\s*(?:Cookie|Set-Cookie)\s*:\s*)[^\r\n]*$""",
    )
    private val cookieQuotedField = Regex(
        """(?i)(["']?(?:cookie|set-cookie)["']?\s*[:=]\s*)(["'])(.*?)\2""",
    )
    private val cookieField = Regex(
        """(?i)(\b(?:cookie|set-cookie)\b\h*[:=]\h*+)(?!\[REDACTED])([^\r\n,}]+)""",
    )

    private const val SECRET_NAME =
        """password|passwd|pwd|token|access[_-]?token|refresh[_-]?token|id[_-]?token|""" +
            """api[_-]?key|apikey|signature|session(?:[_-]?id)?|jwt"""
    private val quotedSecretField = Regex(
        """(?i)(["']?(?:$SECRET_NAME)["']?\s*[:=]\s*)(["'])(.*?)\2""",
    )
    private val unquotedSecretField = Regex(
        """(?i)(\b(?:$SECRET_NAME)\b\s*[:=]\s*)(?!\[REDACTED])([^\s,;&#}"'\]]+)""",
    )
    private val sensitiveUrlParameter = Regex(
        """(?i)([?&](?:$SECRET_NAME|auth|authorization|sig|key|kid|k)=)(?!\[REDACTED])([^&#\s"'<>]+)""",
    )
    private val jwt = Regex(
        """(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?![A-Za-z0-9_-])""",
    )

    private val quotedDrmField = Regex(
        """(?i)(["'](?:k|kid|key|drm[_-]?key|clear[_-]?key)["']\s*:\s*)(["'])(.*?)\2""",
    )
    private val explicitDrmField = Regex(
        """(?i)(\b(?:kid|drm[_-]?key|clear[_-]?key)\b\s*[:=]\s*)(?!\[REDACTED])([^\s,;}"'\]]+)""",
    )
    private val diagnosticLine = Regex("""(?m)^[^\r\n]+""")
    private val drmContext = Regex("""(?i)\b(?:drm|clearkey|clear[_-]?key)\b""")
    private val contextualDrmKey = Regex(
        """(?i)(\b(?:key|k)\b\h*[:=]\h*+)(?!\[REDACTED])([^\s,;}"'\]]+)""",
    )

    private val macAddress = Regex(
        """(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])""",
    )
    private val ipv4Address = Regex(
        """(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])""",
    )
    private val windowsUserPath = Regex(
        """(?i)(\b[A-Z]:[\\/](?:Users|Documents and Settings)[\\/])([^\\/\r\n]+)""",
    )
    private val unixUserPath = Regex(
        """(?i)(/(?:home|Users)/)([^/\s"'\\]+)""",
    )

    fun sanitize(input: String): String {
        if (input.isEmpty()) return input

        var output = input

        output = authorizationHeader.replace(output) { match ->
            match.groupValues[1] + optionalScheme(match.groupValues[2]) + SECRET
        }
        output = authorizationQuotedField.replace(output) { match ->
            match.groupValues[1] +
                match.groupValues[2] +
                optionalScheme(match.groupValues[3]) +
                SECRET +
                match.groupValues[2]
        }
        output = authorizationField.replace(output) { match ->
            match.groupValues[1] + optionalScheme(match.groupValues[2]) + SECRET
        }
        output = bearerCredential.replace(output) { match ->
            "${match.groupValues[1]} $SECRET"
        }

        output = cookieHeader.replace(output) { match -> match.groupValues[1] + SECRET }
        output = cookieQuotedField.replace(output) { match ->
            match.groupValues[1] + match.groupValues[2] + SECRET + match.groupValues[2]
        }
        output = cookieField.replace(output) { match -> match.groupValues[1] + SECRET }

        output = sensitiveUrlParameter.replace(output) { match ->
            match.groupValues[1] + SECRET
        }
        output = quotedSecretField.replace(output) { match ->
            match.groupValues[1] + match.groupValues[2] + SECRET + match.groupValues[2]
        }
        output = unquotedSecretField.replace(output) { match ->
            match.groupValues[1] + SECRET
        }
        output = jwt.replace(output, SECRET)

        output = quotedDrmField.replace(output) { match ->
            match.groupValues[1] + match.groupValues[2] + SECRET + match.groupValues[2]
        }
        output = explicitDrmField.replace(output) { match ->
            match.groupValues[1] + SECRET
        }
        output = diagnosticLine.replace(output) { line ->
            if (drmContext.containsMatchIn(line.value)) {
                contextualDrmKey.replace(line.value) { match ->
                    match.groupValues[1] + SECRET
                }
            } else {
                line.value
            }
        }

        output = macAddress.replace(output, MAC_ADDRESS)
        output = ipv4Address.replace(output, IP_ADDRESS)
        output = redactIpv6(output)

        output = windowsUserPath.replace(output) { match ->
            match.groupValues[1] + USERNAME
        }
        output = unixUserPath.replace(output) { match ->
            match.groupValues[1] + USERNAME
        }

        return output
    }

    private fun optionalScheme(scheme: String): String =
        scheme.takeIf(String::isNotEmpty)?.let { "$it " }.orEmpty()

    private fun redactIpv6(input: String): String {
        val output = StringBuilder(input.length)
        var index = 0
        while (index < input.length) {
            val bracketed = input[index] == '['
            val addressStart = if (bracketed) index + 1 else index
            if (addressStart >= input.length || !input[addressStart].isIpv6HexOrColon()) {
                output.append(input[index++])
                continue
            }

            var addressEnd = addressStart
            while (addressEnd < input.length && input[addressEnd].isIpv6HexOrColon()) {
                addressEnd++
            }
            val closesBracket = bracketed && addressEnd < input.length && input[addressEnd] == ']'
            val address = input.substring(addressStart, addressEnd)
            if (isSyntacticallyIpv6(address)) {
                output.append(IP_ADDRESS)
                index = if (closesBracket) addressEnd + 1 else addressEnd
            } else {
                output.append(input[index])
                index++
            }
        }
        return output.toString()
    }

    private fun Char.isIpv6HexOrColon(): Boolean =
        this == ':' || isDigit() || lowercaseChar() in 'a'..'f'

    /**
     * Validates the hexadecimal form locally. InetAddress.getByName must not be
     * used here: diagnostics contain thousands of timestamps with colons and a
     * resolver call for every candidate can stall report creation for minutes.
     */
    private fun isSyntacticallyIpv6(address: String): Boolean {
        if (address.isBlank() || address.any { it != ':' && !it.isDigit() && it.lowercaseChar() !in 'a'..'f' }) {
            return false
        }
        if (address.count { it == ':' } < 2 || address.contains(":::")) return false
        val compressed = address.indexOf("::")
        if (compressed >= 0 && address.indexOf("::", compressed + 2) >= 0) return false

        val groups = address.split(':').filter(String::isNotEmpty)
        if (groups.any { it.length !in 1..4 }) return false
        return if (compressed >= 0) {
            groups.size < 8
        } else {
            groups.size == 8
        }
    }
}
