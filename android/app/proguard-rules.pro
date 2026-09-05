# kotlinx-serialization — published consumer rules
# (https://github.com/Kotlin/kotlinx.serialization/blob/master/rules/common.pro)
# Keep the generated *$Companion.serializer() lookup path and the
# @Serializable classes/fields R8 would otherwise treat as unused, since
# they're only reached reflectively by the serialization plugin at runtime.
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt

# Keep Serializer for classes with companion objects.
-if @kotlinx.serialization.Serializable class **
-keepclassmembers class <1> {
    static <1>$Companion Companion;
}

# Keep Serializers for classes with named companion objects.
-if @kotlinx.serialization.Serializable class ** {
    static **$* *;
}
-keepclassmembers class <1>$<3> {
    kotlinx.serialization.KSerializer serializer(...);
}

# Keep Serializers for classes with custom companion objects.
-if @kotlinx.serialization.Serializable class ** {
    static ** Companion;
}
-keepclassmembers class <1> {
    static <1> Companion;
}
-if @kotlinx.serialization.Serializable class ** {
    static **$Companion *;
}
-keepclassmembers class <1>$Companion {
    kotlinx.serialization.KSerializer serializer(...);
}

# Keep our own @Serializable DTOs and their fields (Dtos.kt, domain models) —
# names must survive since kotlinx-serialization matches JSON keys either by
# reflection over the generated descriptor or by @SerialName.
-keepclassmembers @kotlinx.serialization.Serializable class app.mealsy.** {
    <fields>;
    <methods>;
}
-keep,includedescriptorclasses class app.mealsy.**$$serializer { *; }
-keepclassmembers class app.mealsy.** {
    *** Companion;
}
-keepclasseswithmembers class app.mealsy.** {
    kotlinx.serialization.KSerializer serializer(...);
}

# Belt-and-braces: ItemDto's custom @Serializable(with = ...) object
# (Dtos.kt) is referenced by name in the annotation rather than by a normal
# call site, so keep it explicitly in case it's ever looked up reflectively.
-keep class app.mealsy.data.api.ItemDtoSerializer { *; }

# Retrofit — published consumer rules
# (https://github.com/square/retrofit/blob/master/retrofit/src/main/resources/META-INF/proguard/retrofit2.pro)
-dontwarn okhttp3.**
-dontwarn okio.**
-dontwarn javax.annotation.**
-dontwarn kotlin.Unit
-dontwarn retrofit2.KotlinExtensions
-dontwarn retrofit2.KotlinExtensions$*
-if interface * { @retrofit2.http.* <methods>; }
-keep,allowobfuscation interface <1>
-if interface * { @retrofit2.http.* <methods>; }
-keep,allowobfuscation,allowshrinking class kotlin.coroutines.Continuation
-keepattributes Signature, RuntimeVisibleAnnotations, RuntimeVisibleParameterAnnotations, AnnotationDefault
-keep,allowobfuscation,allowshrinking class retrofit2.Response

# OkHttp — published consumer rules
# (https://github.com/square/okhttp/blob/master/okhttp/src/jvmMain/resources/META-INF/proguard/okhttp3.pro)
-dontwarn org.codehaus.mojo.animal_sniffer.*
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**

# supabase-kt / ktor — reflection-heavy multiplatform client; keep its own
# serializable request/response models and don't warn on JVM-only ktor
# engines this app doesn't ship (ktor-client-okhttp is the only one used).
-keep class io.github.jan.supabase.** { *; }
-dontwarn io.ktor.**
-dontwarn kotlinx.coroutines.debug.**

# slf4j is an optional runtime binding (ktor/okhttp transitive dep); no
# binder is on this app's classpath and none is needed at runtime.
-dontwarn org.slf4j.**

# Hilt/Dagger generated code is covered by AGP's built-in consumer
# proguard rules (androidx.hilt / dagger.android) — nothing extra required
# here; verified via `assembleRelease` succeeding with DI intact.
