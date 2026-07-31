package com.productline.business.api.fault;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
@EnableConfigurationProperties(DemoFaultProperties.class)
public class DemoFaultWebConfiguration implements WebMvcConfigurer {

    private final DemoFaultInterceptor demoFaultInterceptor;

    public DemoFaultWebConfiguration(DemoFaultInterceptor demoFaultInterceptor) {
        this.demoFaultInterceptor = demoFaultInterceptor;
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(demoFaultInterceptor).addPathPatterns("/api/**");
    }
}
