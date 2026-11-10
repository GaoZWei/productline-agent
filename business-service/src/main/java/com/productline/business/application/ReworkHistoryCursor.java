package com.productline.business.application;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.error.InvalidRequestException;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.HexFormat;
import java.util.List;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.stereotype.Component;

/** 实例内签名防止改写上界；重启或跨实例后需重新从首页读取，不把游标当授权凭证。 */
@Component
public class ReworkHistoryCursor {
    private static final long MAX = 9007199254740991L;
    private final byte[] secret = new byte[32];
    private final ObjectMapper mapper;

    public record Window(long after, long upper) {}

    public ReworkHistoryCursor(ObjectMapper mapper) {
        this.mapper = mapper;
        new SecureRandom().nextBytes(secret);
    }

    public String encode(String user, String task, String rework, String kind, Window window) {
        try {
            byte[] payload = mapper.writeValueAsBytes(List.of(1, scope(user, task, rework, kind), window.after(), window.upper()));
            return Base64.getUrlEncoder().withoutPadding().encodeToString(payload) + "."
                    + Base64.getUrlEncoder().withoutPadding().encodeToString(sign(payload));
        } catch (java.io.IOException exception) {
            throw new IllegalStateException("cannot encode history cursor");
        }
    }

    public Window decode(String token, String user, String task, String rework, String kind) {
        try {
            if (token == null || token.length() > 2048 || !token.matches("[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+")) throw invalid();
            String[] parts = token.split("\\.");
            byte[] payload = Base64.getUrlDecoder().decode(parts[0]);
            if (!MessageDigest.isEqual(sign(payload), Base64.getUrlDecoder().decode(parts[1]))) throw invalid();
            var node = mapper.reader().with(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
                    .with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readTree(payload);
            if (node == null || !node.isArray() || node.size() != 4 || !node.get(0).isInt() || node.get(0).intValue() != 1
                    || !node.get(1).isTextual() || !scope(user, task, rework, kind).equals(node.get(1).textValue())
                    || !node.get(2).isIntegralNumber() || !node.get(2).canConvertToLong()
                    || !node.get(3).isIntegralNumber() || !node.get(3).canConvertToLong()) throw invalid();
            long after = node.get(2).longValue();
            long upper = node.get(3).longValue();
            if (after < 1 || upper <= after || upper > MAX) throw invalid();
            return new Window(after, upper);
        } catch (java.io.IOException | IllegalArgumentException exception) {
            throw invalid();
        }
    }

    private String scope(String user, String task, String rework, String kind) {
        try {
            // 绑定完整身份和资源，但不把实际用户标识明文放进可解码的游标。
            byte[] data = mapper.writeValueAsString(List.of(user, task, rework, kind)).getBytes(StandardCharsets.UTF_8);
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(data));
        } catch (java.io.IOException | GeneralSecurityException exception) {
            throw new IllegalStateException("cannot bind history cursor");
        }
    }

    private byte[] sign(byte[] payload) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret, "HmacSHA256"));
            return mac.doFinal(payload);
        } catch (GeneralSecurityException exception) {
            throw new IllegalStateException("cannot sign history cursor");
        }
    }

    private InvalidRequestException invalid() {
        return new InvalidRequestException("history cursor is invalid or does not match this request");
    }
}
