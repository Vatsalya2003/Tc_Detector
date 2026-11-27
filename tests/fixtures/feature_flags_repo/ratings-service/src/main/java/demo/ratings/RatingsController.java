package demo.ratings;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
class RatingsController {

    @Value("${ratings.show-stars:false}")
    private boolean showStars;

    @Value("${ratings.timeout-ms:500}")
    private int timeoutMs;

    @Value("${spring.cloud.discovery.enabled:true}")
    private boolean discoveryEnabled;

    @Value("${spring.profiles.active:default}")
    private String activeProfile;

    @GetMapping("/ratings")
    String ratings() {
        // POSITIVE B: an if on a @Value boolean app flag.
        if (showStars) {
            return "stars";
        }
        // NEGATIVE: a timeout is config, not an on/off flag.
        if (timeoutMs > 1000) {
            return "slow";
        }
        // NEGATIVE: a framework switch (spring.*).
        if (discoveryEnabled) {
            return "discovered";
        }
        // NEGATIVE: spring.profiles.active is not a flag.
        if ("production".equals(activeProfile)) {
            return "prod";
        }
        return "plain";
    }
}
