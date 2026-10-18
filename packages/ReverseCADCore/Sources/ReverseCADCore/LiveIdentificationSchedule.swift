import Foundation

/// A latest-frame schedule: no queued frames, no catch-up bursts, no old replies after restart.
public struct LiveIdentificationSchedule {
    public struct Ticket: Equatable {
        public let id: UUID
        public let sequence: Int
        public let sentAt: TimeInterval
    }
    public static let interval: TimeInterval = 0.2
    public static let maximumAge: TimeInterval = 1.2
    public static let maximumInFlight = 4
    public private(set) var running = false
    public private(set) var inFlight: [UUID: Ticket] = [:]
    private var nextSend: TimeInterval = 0
    private var sequence = 0
    private var appliedSequence = -1
    private var failures = 0

    public init() {}
    public mutating func start(at now: TimeInterval) {
        self = Self(); running = true; nextSend = now
    }
    public mutating func stop() { running = false; inFlight.removeAll() }
    public mutating func reserve(at now: TimeInterval) -> Ticket? {
        guard running, now >= nextSend, inFlight.count < Self.maximumInFlight else { return nil }
        let ticket = Ticket(id: UUID(), sequence: sequence, sentAt: now)
        sequence += 1; nextSend = now + Self.interval
        inFlight[ticket.id] = ticket
        return ticket
    }
    /// Call for every completed reply, including a negative detection, before changing the UI.
    public mutating func complete(_ ticket: Ticket, at now: TimeInterval, includingExpired: Bool = false) -> Bool {
        guard running, inFlight.removeValue(forKey: ticket.id) == ticket,
              ticket.sequence > appliedSequence, now >= ticket.sentAt,
              includingExpired || now - ticket.sentAt <= Self.maximumAge else { return false }
        appliedSequence = ticket.sequence
        return true
    }
    public mutating func succeeded() { failures = 0 }
    public mutating func failed(at now: TimeInterval) {
        failures = min(3, failures + 1)
        nextSend = max(nextSend, now + pow(2, Double(failures)))
    }
}
