package demo.ratings;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

@Configuration
class RatingsConfig {

    // POSITIVE A: the guideline's own example.
    @Bean
    @ConditionalOnProperty(name = "petclinic.features.vet-ratings", havingValue = "true")
    VetRatingService vetRatingService() {
        return new VetRatingService();
    }

    // POSITIVE A: prefix + name, over several lines.
    @Bean
    @ConditionalOnProperty(
            prefix = "ratings.beta",
            name = "enabled",
            havingValue = "true")
    BetaRatingService betaRatingService() {
        return new BetaRatingService();
    }

    // NEGATIVE: a framework switch (spring.*), not an app feature.
    @Bean
    @ConditionalOnProperty(name = "spring.cache.enabled", havingValue = "true")
    RatingCache ratingCache() {
        return new RatingCache();
    }

    // NEGATIVE: Actuator switch given as prefix + name.
    @Bean
    @ConditionalOnProperty(prefix = "management.metrics", name = "enabled")
    RatingMetrics ratingMetrics() {
        return new RatingMetrics();
    }

    // NEGATIVE: a profile switches a whole environment, not one feature.
    @Bean
    @Profile("production")
    RatingWarmup ratingWarmup() {
        return new RatingWarmup();
    }

    // NEGATIVE: commented out, so not in the code.
    // @ConditionalOnProperty(name = "ratings.legacy.enabled")
}
