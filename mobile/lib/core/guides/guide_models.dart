/// Models for local session transcripts and visual recall guides.
library;

class GuideStepItem {
  final String id;
  final int stepNumber;
  final String title;
  final String instruction;
  final String? imageUrl;
  final String? localImagePath;
  final DateTime createdAt;

  const GuideStepItem({
    required this.id,
    required this.stepNumber,
    required this.title,
    required this.instruction,
    this.imageUrl,
    this.localImagePath,
    required this.createdAt,
  });

  factory GuideStepItem.fromJson(Map<String, dynamic> json) {
    return GuideStepItem(
      id: json['id'] as String? ?? '',
      stepNumber: (json['step_number'] as num?)?.toInt() ?? 1,
      title: json['title'] as String? ?? '',
      instruction: json['instruction'] as String? ?? '',
      imageUrl: json['image_url'] as String?,
      localImagePath: json['local_image_path'] as String?,
      createdAt:
          DateTime.tryParse(json['created_at'] as String? ?? '') ??
          DateTime.now(),
    );
  }

  Map<String, dynamic> toJson() => {
    'id': id,
    'step_number': stepNumber,
    'title': title,
    'instruction': instruction,
    'image_url': imageUrl,
    'local_image_path': localImagePath,
    'created_at': createdAt.toIso8601String(),
  };
}

class SessionGuideItem {
  final String id;
  final String? sessionId;
  final String title;
  final String summary;
  final String category;
  final int stepsCount;
  final DateTime createdAt;
  final List<GuideStepItem> steps;
  final String transcript;
  final bool isLocal;

  const SessionGuideItem({
    required this.id,
    this.sessionId,
    required this.title,
    required this.summary,
    required this.category,
    required this.stepsCount,
    required this.createdAt,
    this.steps = const [],
    this.transcript = '',
    this.isLocal = false,
  });

  factory SessionGuideItem.fromJson(Map<String, dynamic> json) {
    final rawSteps = json['steps'] as List<dynamic>? ?? [];
    return SessionGuideItem(
      id: json['id'] as String? ?? '',
      sessionId: json['session_id'] as String?,
      title: json['title'] as String? ?? 'Help Guide',
      summary: json['summary'] as String? ?? '',
      category: json['category'] as String? ?? 'general',
      stepsCount: (json['steps_count'] as num?)?.toInt() ?? rawSteps.length,
      createdAt:
          DateTime.tryParse(json['created_at'] as String? ?? '') ??
          DateTime.now(),
      steps: rawSteps
          .map((s) => GuideStepItem.fromJson(s as Map<String, dynamic>))
          .toList(),
      transcript: json['transcript'] as String? ?? '',
      isLocal: json['is_local'] as bool? ?? false,
    );
  }

  Map<String, dynamic> toJson() => {
    'id': id,
    'session_id': sessionId,
    'title': title,
    'summary': summary,
    'category': category,
    'steps_count': steps.length,
    'created_at': createdAt.toIso8601String(),
    'steps': steps.map((step) => step.toJson()).toList(),
    'transcript': transcript,
    'is_local': isLocal,
  };
}
