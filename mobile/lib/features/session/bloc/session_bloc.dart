/// Assistance Session BLoC State Management.
///
/// Manages session state transitions: SessionInitial -> SessionConnecting -> SessionActive -> SessionEnded.

abstract class SessionEvent {}

class CreateSessionEvent extends SessionEvent {
  final String title;
  CreateSessionEvent({required this.title});
}

class JoinSessionEvent extends SessionEvent {
  final String sessionCode;
  JoinSessionEvent({required this.sessionCode});
}

class LeaveSessionEvent extends SessionEvent {}
class EndSessionEvent extends SessionEvent {}

abstract class SessionState {
  final String? sessionId;
  final String status;
  SessionState({this.sessionId, required this.status});
}

class SessionInitial extends SessionState {
  SessionInitial() : super(status: 'initial');
}

class SessionConnecting extends SessionState {
  SessionConnecting() : super(status: 'connecting');
}

class SessionActive extends SessionState {
  final String sessionCode;
  SessionActive({required String sessionId, required this.sessionCode})
      : super(sessionId: sessionId, status: 'active');
}

class SessionEnded extends SessionState {
  SessionEnded({String? sessionId}) : super(sessionId: sessionId, status: 'ended');
}

class SessionError extends SessionState {
  final String message;
  SessionError(this.message) : super(status: 'error');
}

class SessionBloc {
  SessionState _state = SessionInitial();
  SessionState get state => _state;

  Future<void> handleEvent(SessionEvent event) async {
    if (event is CreateSessionEvent) {
      _state = SessionConnecting();
      await Future.delayed(const Duration(milliseconds: 20));
      _state = SessionActive(sessionId: 'sess_123', sessionCode: '123456');
    } else if (event is JoinSessionEvent) {
      _state = SessionConnecting();
      await Future.delayed(const Duration(milliseconds: 20));
      _state = SessionActive(sessionId: 'sess_123', sessionCode: event.sessionCode);
    } else if (event is LeaveSessionEvent || event is EndSessionEvent) {
      _state = SessionEnded(sessionId: _state.sessionId);
    }
  }
}
