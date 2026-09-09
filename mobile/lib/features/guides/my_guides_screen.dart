/// My Guides screen — browsing and searching saved step-by-step session guides.
library;

import 'dart:convert';
import 'package:flutter/material.dart';

import '../../core/guides/guide_models.dart';
import '../../core/network/api_client.dart';
import '../../theme/app_theme.dart';
import 'guide_detail_screen.dart';

class MyGuidesScreen extends StatefulWidget {
  final ApiClient apiClient;

  const MyGuidesScreen({super.key, required this.apiClient});

  @override
  State<MyGuidesScreen> createState() => _MyGuidesScreenState();
}

class _MyGuidesScreenState extends State<MyGuidesScreen> {
  List<SessionGuideItem> _guides = [];
  bool _loading = true;
  String _searchQuery = '';
  final TextEditingController _searchController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _fetchGuides();
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _fetchGuides() async {
    setState(() => _loading = true);
    try {
      final resp = await widget.apiClient.get('/guides');
      if (resp.statusCode == 200) {
        final List<dynamic> data = jsonDecode(resp.body);
        if (mounted) {
          setState(() {
            _guides = data
                .map((g) => SessionGuideItem.fromJson(g as Map<String, dynamic>))
                .toList();
            _loading = false;
          });
        }
      } else {
        if (mounted) setState(() => _loading = false);
      }
    } catch (e) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _deleteGuide(String guideId) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.bgSecondary,
        title: const Text('Delete Guide?'),
        content: const Text('This will remove this saved step-by-step guide from your history.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: AppTheme.accentRose),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );

    if (confirm != true) return;

    try {
      await widget.apiClient.delete('/guides/$guideId');
      setState(() {
        _guides.removeWhere((g) => g.id == guideId);
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Guide deleted')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to delete guide: $e')),
        );
      }
    }
  }

  IconData _getCategoryIcon(String category) {
    switch (category.toLowerCase()) {
      case 'settings':
        return Icons.settings_suggest;
      case 'wifi':
      case 'connectivity':
        return Icons.wifi;
      case 'sound':
      case 'volume':
        return Icons.volume_up;
      case 'display':
        return Icons.brightness_medium;
      default:
        return Icons.auto_stories;
    }
  }

  List<SessionGuideItem> get _filteredGuides {
    if (_searchQuery.trim().isEmpty) return _guides;
    final query = _searchQuery.toLowerCase();
    return _guides.where((g) {
      return g.title.toLowerCase().contains(query) ||
          g.summary.toLowerCase().contains(query) ||
          g.category.toLowerCase().contains(query);
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    final filtered = _filteredGuides;

    return Scaffold(
      backgroundColor: AppTheme.bgPrimary,
      appBar: AppBar(
        backgroundColor: AppTheme.bgSecondary,
        title: const Text(
          'My Step Guides',
          style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
        ),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => Navigator.pop(context),
        ),
      ),
      body: SafeArea(
        child: Column(
          children: [
            // Search Bar
            Container(
              padding: const EdgeInsets.all(16),
              color: AppTheme.bgSecondary,
              child: TextField(
                controller: _searchController,
                style: const TextStyle(color: Colors.white, fontSize: 16),
                decoration: InputDecoration(
                  hintText: 'Search guides (e.g. language, wifi)...',
                  hintStyle: const TextStyle(color: AppTheme.textMuted),
                  prefixIcon: const Icon(Icons.search, color: AppTheme.accentEmerald),
                  suffixIcon: _searchQuery.isNotEmpty
                      ? IconButton(
                          icon: const Icon(Icons.clear, color: AppTheme.textMuted),
                          onPressed: () {
                            _searchController.clear();
                            setState(() => _searchQuery = '');
                          },
                        )
                      : null,
                  filled: true,
                  fillColor: AppTheme.bgPrimary,
                  contentPadding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(14),
                    borderSide: BorderSide.none,
                  ),
                ),
                onChanged: (val) => setState(() => _searchQuery = val),
              ),
            ),

            // Guides List
            Expanded(
              child: _loading
                  ? const Center(child: CircularProgressIndicator(color: AppTheme.accentEmerald))
                  : filtered.isEmpty
                      ? RefreshIndicator(
                          onRefresh: _fetchGuides,
                          color: AppTheme.accentEmerald,
                          child: ListView(
                            physics: const AlwaysScrollableScrollPhysics(),
                            children: [
                              SizedBox(height: MediaQuery.of(context).size.height * 0.2),
                              Center(
                                child: Padding(
                                  padding: const EdgeInsets.symmetric(horizontal: 32),
                                  child: Column(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Container(
                                        padding: const EdgeInsets.all(20),
                                        decoration: BoxDecoration(
                                          color: AppTheme.accentEmerald.withValues(alpha: 0.1),
                                          shape: BoxShape.circle,
                                        ),
                                        child: const Icon(
                                          Icons.menu_book,
                                          size: 56,
                                          color: AppTheme.accentEmerald,
                                        ),
                                      ),
                                      const SizedBox(height: 20),
                                      Text(
                                        _searchQuery.isEmpty ? 'No Guides Saved Yet' : 'No Matching Guides',
                                        style: const TextStyle(
                                          color: Colors.white,
                                          fontSize: 20,
                                          fontWeight: FontWeight.w800,
                                        ),
                                      ),
                                      const SizedBox(height: 10),
                                      Text(
                                        _searchQuery.isEmpty
                                            ? 'When someone helps you on a call, AssistMe creates step-by-step visual guides here so you can review them anytime without feeling like asking again.'
                                            : 'Try searching with a different keyword.',
                                        textAlign: TextAlign.center,
                                        style: const TextStyle(color: AppTheme.textSecondary, fontSize: 15, height: 1.4),
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                            ],
                          ),
                        )
                      : RefreshIndicator(
                          onRefresh: _fetchGuides,
                          color: AppTheme.accentEmerald,
                          child: ListView.separated(
                            padding: const EdgeInsets.all(16),
                            itemCount: filtered.length,
                            separatorBuilder: (context, index) => const SizedBox(height: 12),
                            itemBuilder: (context, index) {
                              final guide = filtered[index];
                              return InkWell(
                                borderRadius: BorderRadius.circular(16),
                                onTap: () {
                                  Navigator.push(
                                    context,
                                    MaterialPageRoute(
                                      builder: (_) => GuideDetailScreen(guide: guide),
                                    ),
                                  );
                                },
                                child: Container(
                                  padding: const EdgeInsets.all(16),
                                  decoration: BoxDecoration(
                                    color: AppTheme.bgSecondary,
                                    borderRadius: BorderRadius.circular(16),
                                    border: Border.all(color: Colors.white10),
                                    boxShadow: const [
                                      BoxShadow(color: Colors.black26, blurRadius: 6, offset: Offset(0, 2)),
                                    ],
                                  ),
                                  child: Row(
                                    children: [
                                      Container(
                                        padding: const EdgeInsets.all(14),
                                        decoration: BoxDecoration(
                                          color: AppTheme.accentEmerald.withValues(alpha: 0.15),
                                          borderRadius: BorderRadius.circular(14),
                                        ),
                                        child: Icon(
                                          _getCategoryIcon(guide.category),
                                          color: AppTheme.accentEmerald,
                                          size: 30,
                                        ),
                                      ),
                                      const SizedBox(width: 16),
                                      Expanded(
                                        child: Column(
                                          crossAxisAlignment: CrossAxisAlignment.start,
                                          children: [
                                            Text(
                                              guide.title,
                                              style: const TextStyle(
                                                color: Colors.white,
                                                fontSize: 17,
                                                fontWeight: FontWeight.w800,
                                              ),
                                              maxLines: 1,
                                              overflow: TextOverflow.ellipsis,
                                            ),
                                            const SizedBox(height: 4),
                                            if (guide.summary.isNotEmpty)
                                              Text(
                                                guide.summary,
                                                style: const TextStyle(
                                                  color: AppTheme.textSecondary,
                                                  fontSize: 13,
                                                ),
                                                maxLines: 2,
                                                overflow: TextOverflow.ellipsis,
                                              ),
                                            const SizedBox(height: 8),
                                            Row(
                                              children: [
                                                Container(
                                                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                                                  decoration: BoxDecoration(
                                                    color: AppTheme.accentEmerald.withValues(alpha: 0.2),
                                                    borderRadius: BorderRadius.circular(6),
                                                  ),
                                                  child: Text(
                                                    '${guide.stepsCount} steps',
                                                    style: const TextStyle(
                                                      color: AppTheme.accentEmerald,
                                                      fontSize: 11,
                                                      fontWeight: FontWeight.w700,
                                                    ),
                                                  ),
                                                ),
                                                const SizedBox(width: 8),
                                                Text(
                                                  '${guide.createdAt.day}/${guide.createdAt.month}/${guide.createdAt.year}',
                                                  style: const TextStyle(
                                                    color: AppTheme.textMuted,
                                                    fontSize: 11,
                                                  ),
                                                ),
                                              ],
                                            ),
                                          ],
                                        ),
                                      ),
                                      IconButton(
                                        icon: const Icon(Icons.delete_outline, color: AppTheme.textMuted, size: 20),
                                        onPressed: () => _deleteGuide(guide.id),
                                      ),
                                    ],
                                  ),
                                ),
                              );
                            },
                          ),
                        ),
            ),
          ],
        ),
      ),
    );
  }
}
