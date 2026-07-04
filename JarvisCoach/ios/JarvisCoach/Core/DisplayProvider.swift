import Foundation

protocol DisplayProvider {
    func display(text: String)
}

/// 当前版本在 iPhone 屏幕上直接显示 HUD，未来可扩展为眼镜 / 外接屏实现。
final class PhoneDisplayProvider: DisplayProvider {
    func display(text: String) {
        // 预留接口：当前由 SwiftUI 视图直接绑定 SessionViewModel.suggestion.text。
        // 未来可以在这里接入外部显示设备的更新逻辑。
    }
}

