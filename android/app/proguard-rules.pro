# Add project specific ProGuard rules here.

# Keep the network + serialization types.
-keepattributes Signature, *Annotation*
-keepclassmembers,allowobfuscation class * {
    @kotlinx.serialization.SerialName <fields>;
}
-keep class kotlinx.serialization.** { *; }
-keep class com.example.remotepanel.network.** { *; }
-keep class com.example.remotepanel.data.** { *; }

# OkHttp
-dontwarn okhttp3.**
-dontwarn okio.**