package dev.idaten.companion.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

interface TokenStore {
    fun read(): String?

    fun write(token: String)

    fun clear()
}

class AndroidKeystoreTokenStore(
    context: Context,
) : TokenStore {
    private val preferences = context.getSharedPreferences("device_credentials", Context.MODE_PRIVATE)

    override fun read(): String? {
        val encoded = preferences.getString(CIPHERTEXT, null) ?: return null
        val bytes = Base64.decode(encoded, Base64.NO_WRAP)
        if (bytes.size <= IV_SIZE) return null
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(TAG_BITS, bytes, 0, IV_SIZE))
        return cipher.doFinal(bytes.copyOfRange(IV_SIZE, bytes.size)).decodeToString()
    }

    override fun write(token: String) {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, secretKey())
        val encrypted = cipher.doFinal(token.encodeToByteArray())
        val payload = cipher.iv + encrypted
        preferences.edit().putString(CIPHERTEXT, Base64.encodeToString(payload, Base64.NO_WRAP)).apply()
    }

    override fun clear() {
        preferences.edit().remove(CIPHERTEXT).apply()
    }

    private fun secretKey(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(
                KeyGenParameterSpec
                    .Builder(
                        KEY_ALIAS,
                        KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                    ).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .build(),
            )
            generateKey()
        }
    }

    private companion object {
        const val KEY_ALIAS = "idaten_device_token_v1"
        const val CIPHERTEXT = "ciphertext"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_SIZE = 12
        const val TAG_BITS = 128
    }
}

class InMemoryTokenStore : TokenStore {
    private var token: String? = null

    override fun read(): String? = token

    override fun write(token: String) {
        this.token = token
    }

    override fun clear() {
        token = null
    }
}
