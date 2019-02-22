#include <google/protobuf/text_format.h>
#include <google/protobuf/util/message_differencer.h>
#include <gtest/gtest.h>

#include <cstring>
#include <vector>

#include "src/stirling/bcc_connector.h"
#include "src/stirling/info_class_schema.h"
#include "src/stirling/pub_sub_manager.h"
#include "src/stirling/source_connector.h"

namespace pl {
namespace stirling {

using google::protobuf::TextFormat;
using google::protobuf::util::MessageDifferencer;
using stirlingpb::Element_State;
using stirlingpb::InfoClass;
using types::DataType;

const char* kInfoClassSchema = R"(
  name : "cpu_usage",
  elements {
    name: "user_percentage",
    type: FLOAT64,
  }
  elements {
    name: "system_percentage",
    type: FLOAT64,
  }
  elements {
    name: "io_percentage",
    type: FLOAT64,
  }
  metadata {
    key: "source"
    value: "ebpf_cpu_metrics"
  }
)";

class PubSubManagerTest : public ::testing::Test {
 protected:
  PubSubManagerTest()
      : element_1("user_percentage", DataType::FLOAT64,
                  Element_State::Element_State_NOT_SUBSCRIBED),
        element_2("system_percentage", DataType::FLOAT64,
                  Element_State::Element_State_NOT_SUBSCRIBED),
        element_3("io_percentage", DataType::FLOAT64, Element_State::Element_State_NOT_SUBSCRIBED) {
  }
  void SetUp() override {
    source_ = BCCCPUMetricsConnector::Create();
    pub_sub_manager_schemas_.push_back(std::make_unique<InfoClassSchema>("cpu_usage"));
    pub_sub_manager_schemas_[0]->SetSourceConnector(source_.get());

    pub_sub_manager_schemas_[0]->AddElement(element_1);
    pub_sub_manager_schemas_[0]->AddElement(element_2);
    pub_sub_manager_schemas_[0]->AddElement(element_3);

    pub_sub_manager_ = std::make_unique<PubSubManager>(pub_sub_manager_schemas_);
  }

  std::unique_ptr<SourceConnector> source_;
  std::unique_ptr<PubSubManager> pub_sub_manager_;
  std::vector<std::unique_ptr<InfoClassSchema>> pub_sub_manager_schemas_;
  InfoClassElement element_1, element_2, element_3;
};

// This test validates that the Publish proto generated by the PubSubManager
// matches the expected Publish proto message (based on kInfoClassSchema proto
// and with some fields added in the test).
TEST_F(PubSubManagerTest, publish_test) {
  // Publish info classes using proto message.
  stirlingpb::Publish actual_publish_pb;
  actual_publish_pb = pub_sub_manager_->GeneratePublishProto();

  // Set expectations for the publish message.
  stirlingpb::Publish expected_publish_pb;
  auto expected_info_class = expected_publish_pb.add_published_info_classes();
  EXPECT_TRUE(TextFormat::MergeFromString(kInfoClassSchema, expected_info_class));
  expected_info_class->set_id(0);
  for (int element_idx = 0; element_idx < expected_info_class->elements_size(); ++element_idx) {
    expected_info_class->mutable_elements(element_idx)
        ->set_state(Element_State::Element_State_NOT_SUBSCRIBED);
  }

  EXPECT_EQ(1, expected_publish_pb.published_info_classes_size());
  EXPECT_EQ(0, actual_publish_pb.published_info_classes(0).id());
  EXPECT_TRUE(MessageDifferencer::Equals(actual_publish_pb, expected_publish_pb));
}

// This test validates that the InfoClassSchema objects have their subscriptions
// updated after the PubSubManager reads a subscribe message (from an agent). The
// subscribe message is created using kInfoClassSchema proto message and with fields from
// a Publish proto message.
TEST_F(PubSubManagerTest, subscribe_test) {
  // Do the publish.
  stirlingpb::Publish publish_pb;
  publish_pb = pub_sub_manager_->GeneratePublishProto();

  // Get a subscription from an upstream agent.
  stirlingpb::Subscribe subscribe_pb;
  auto info_class = subscribe_pb.add_subscribed_info_classes();
  EXPECT_TRUE(TextFormat::MergeFromString(kInfoClassSchema, info_class));

  // The subscribe message needs ids from the publish message and also
  // update the subscriptions for elements.
  size_t id = publish_pb.published_info_classes(0).id();
  info_class->set_id(id);
  for (int element_idx = 0; element_idx < info_class->elements_size(); ++element_idx) {
    info_class->mutable_elements(element_idx)->set_state(Element_State::Element_State_SUBSCRIBED);
  }

  // Update the InfoClassSchema objects with the subscribe message.
  EXPECT_EQ(Status::OK(), pub_sub_manager_->UpdateSchemaFromSubscribe(subscribe_pb));
  // Verify updated subscriptions.
  for (auto& info_class_schema : pub_sub_manager_->config_schemas()) {
    for (size_t idx = 0; idx < info_class_schema->NumElements(); ++idx) {
      auto element = info_class_schema->GetElement(idx);
      EXPECT_EQ(element.state(), Element_State::Element_State_SUBSCRIBED);
    }
  }
}

}  // namespace stirling
}  // namespace pl
