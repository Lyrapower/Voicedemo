import Foundation

final class Debouncer {
    private let interval: TimeInterval
    private var workItem: DispatchWorkItem?

    init(interval: TimeInterval) {
        self.interval = interval
    }

    func execute(_ block: @escaping () -> Void) {
        workItem?.cancel()
        let item = DispatchWorkItem(block: block)
        workItem = item
        DispatchQueue.main.asyncAfter(deadline: .now() + interval, execute: item)
    }
}

