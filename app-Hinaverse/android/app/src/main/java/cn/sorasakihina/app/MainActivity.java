package cn.sorasakihina.app;

import android.webkit.ValueCallback;

import com.getcapacitor.BridgeActivity;

/**
 * 安卓返回键接管：先问远程页面的 window.__hinaBack（frontend device.ts 实现）——
 * "true" = 页面消化了（回聊天页 / 提示再按一次退出），其余情况照常退出。
 * 线上还是旧版站点（没有 __hinaBack）时返回 "false"，保持默认行为，新旧部署无顺序依赖。
 */
public class MainActivity extends BridgeActivity {

    @Override
    public void onBackPressed() {
        if (getBridge() == null || getBridge().getWebView() == null) {
            super.onBackPressed();
            return;
        }
        getBridge().getWebView().evaluateJavascript(
                "window.__hinaBack ? String(window.__hinaBack()) : 'false'",
                new ValueCallback<String>() {
                    @Override
                    public void onReceiveValue(String result) {
                        // evaluateJavascript 回传的是 JSON，字符串自带引号
                        if ("\"true\"".equals(result)) {
                            return; // 页面已消化这次返回
                        }
                        MainActivity.super.onBackPressed(); // 前端放行（双击确认）或未接管 → 真退出
                    }
                });
    }
}
