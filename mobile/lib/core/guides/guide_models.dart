/// Models for session visual guides and step-by-step recall.
library;

class GuideStepItem {
  final String id;
  final int stepNumber;
  final String title;
  final String instruction;
  final String? imageUrl;
  final DateTime createdAt;

  const GuideStepItem({
    required this.id,
    required this.stepNumber,
    required this.title,
    required this.instruction,
    this.imageUrl,
    required this.createdAt,
  });

  factory GuideStepItem.fromJson(Map<String, dynamic> json) {
    return GuideStepItem(
      id: json['id'] as String? ?? '',
      stepNumber: (json['step_number'] as num?)?.toInt() ?? 1,
      title: json['title'] as String? ?? '',
      instruction: json['instruction'] as String? ?? '',
      imageUrl: json['image_url'] as String?,
      createdAt: DateTime.tryParse(json['created_at'] as String? ?? '') ?? DateTime.now(),
    );
  }
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

  const SessionGuideItem({
    required this.id,
    this.sessionId,
    required this.title,
    required this.summary,
    required this.category,
    required this.stepsCount,
    required this.createdAt,
    this.steps = const [],
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
      createdAt: DateTime.tryParse(json['created_at'] as String? ?? '') ?? DateTime.now(),
      steps: rawSteps.map((s) => GuideStepItem.fromJson(s as Map<String, dynamic>)).toList(),
    );
  }
}
