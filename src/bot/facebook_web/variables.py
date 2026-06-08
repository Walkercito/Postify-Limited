"""Build the ``variables`` payload for the group ComposerStoryCreateMutation.

This is the *fixed Comet payload skeleton* referenced in :mod:`bot.constants`:
the meaningful, tunable scalars (entry point, surface, render location, …) come
from named constants, while the surrounding structural keys are the wire schema
of the persisted GraphQL query and stay inline here — there is exactly one place
that knows this shape. The null/false cosmetic fields are preserved verbatim:
the persisted query validates ``variables`` against its declared inputs, so a
dropped field risks a ``missing_required_variable_value`` rejection.
"""

from __future__ import annotations

from bot.constants import (
    FB_WEB_CLIENT_MUTATION_ID,
    FB_WEB_COMPOSER_ENTRY_POINT,
    FB_WEB_COMPOSER_SOURCE,
    FB_WEB_COMPOSER_SOURCE_SURFACE_GROUP,
    FB_WEB_COMPOSER_TYPE_GROUP,
    FB_WEB_EVENT_SHARE_SURFACE,
    FB_WEB_FEED_LOCATION_GROUP,
    FB_WEB_GROUP_ATTRIBUTION_ID,
    FB_WEB_GROUP_COMMENTS_KEY,
    FB_WEB_PRIVACY_SELECTOR_RENDER_LOCATION,
    FB_WEB_RENDER_LOCATION_GROUP,
    FB_WEB_SCALE,
)


def build_group_post_variables(
    *,
    group_id: str,
    message: str,
    actor_id: str,
    session_id: str,
    photo_ids: list[str],
) -> dict[str, object]:
    """Assemble the ComposerStoryCreateMutation ``variables`` for a group post.

    ``photo_ids`` are the ids returned by the photo-upload step; each becomes a
    ``{"photo": {"id": …}}`` attachment. An empty list posts text only.
    """
    attachments = [{"photo": {"id": photo_id}} for photo_id in photo_ids]
    return {
        "input": {
            "composer_entry_point": FB_WEB_COMPOSER_ENTRY_POINT,
            "composer_source_surface": FB_WEB_COMPOSER_SOURCE_SURFACE_GROUP,
            "composer_type": FB_WEB_COMPOSER_TYPE_GROUP,
            "logging": {"composer_session_id": session_id},
            "source": FB_WEB_COMPOSER_SOURCE,
            "attachments": attachments,
            "message": {"ranges": [], "text": message},
            "with_tags_ids": [],
            "inline_activities": [],
            "explicit_place_id": "0",
            "text_format_preset_id": "0",
            "navigation_data": {"attribution_id_v2": FB_WEB_GROUP_ATTRIBUTION_ID},
            "tracking": [None],
            "event_share_metadata": {"surface": FB_WEB_EVENT_SHARE_SURFACE},
            "audience": {"to_id": group_id},
            "actor_id": actor_id,
            "client_mutation_id": FB_WEB_CLIENT_MUTATION_ID,
        },
        "displayCommentsFeedbackContext": None,
        "displayCommentsContextEnableComment": None,
        "displayCommentsContextIsAdPreview": None,
        "displayCommentsContextIsAggregatedShare": None,
        "displayCommentsContextIsStorySet": None,
        "feedLocation": FB_WEB_FEED_LOCATION_GROUP,
        "feedbackSource": 0,
        "focusCommentID": None,
        "gridMediaWidth": None,
        "groupID": None,
        "scale": FB_WEB_SCALE,
        "privacySelectorRenderLocation": FB_WEB_PRIVACY_SELECTOR_RENDER_LOCATION,
        "checkPhotosToReelsUpsellEligibility": False,
        "renderLocation": FB_WEB_RENDER_LOCATION_GROUP,
        "useDefaultActor": False,
        "inviteShortLinkKey": None,
        "isFeed": False,
        "isFundraiser": False,
        "isFunFactPost": False,
        "isGroup": True,
        "isEvent": False,
        "isTimeline": False,
        "isSocialLearning": False,
        "isPageNewsFeed": False,
        "isProfileReviews": False,
        "isWorkSharedDraft": False,
        "UFI2CommentsProvider_commentsKey": FB_WEB_GROUP_COMMENTS_KEY,
        "hashtag": None,
        "canUserManageOffers": False,
        "__relay_internal__pv__CometUFIIsRTAEnabledrelayprovider": False,
        "__relay_internal__pv__CometUFIReactionsEnableShortNamerelayprovider": False,
        "__relay_internal__pv__IsWorkUserrelayprovider": False,
        "__relay_internal__pv__IsMergQAPollsrelayprovider": False,
        "__relay_internal__pv__StoriesArmadilloReplyEnabledrelayprovider": False,
        "__relay_internal__pv__StoriesRingrelayprovider": False,
    }
